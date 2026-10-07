"""Local, resumable Pinterest batches. This module never writes to remote services."""
import argparse
import csv
import hashlib
import json
import os
import re
import sys
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

from pinterest_services import check_short_url, ServiceError

DEFAULT_APPROVED = Path(__file__).resolve().parent.parent / 'Vetted SaaS B - Content Strategy and Growth Strategy/approved-urls.md'
VENDORS = {
    'get.carepatron.com': ('Carepatron', 'Productivity & Efficiency'),
    'get.datahawk.co': ('DataHawk', 'Business Growth Strategies'),
    'try.elevenlabs.io': ('ElevenLabs', 'AI Tools & Automation'),
    'free-trial.adcreative.ai': ('AdCreative.ai', 'AI Tools & Automation'),
    'partners.snowfire.ai': ('Snowfire', 'Business & Entrepreneurship'),
    'trymoo.moosend.com': ('Moosend', 'Business Growth Strategies'),
    'try.getresponsetoday.com': ('GetResponse', 'Business Growth Strategies'),
    'get.socialbee.io': ('SocialBee', 'Business Growth Strategies'),
    'join.rankprompt.com': ('RankPrompt', 'AI Tools & Automation'),
    'join.glideapps.com': ('Glide', 'AI Tools & Automation'),
    'manychat.partnerlinks.io': ('ManyChat', 'Business Growth Strategies'),
    'try.bidx.io': ('BidX', 'Business Growth Strategies'),
    'try.gelato.com': ('Gelato', 'Side Hustle Ideas'),
    'referral.flippa.com': ('Flippa', 'Business & Entrepreneurship'),
}
# Keep this in sync with the proven Pinterest bulk-upload template. Pinterest's
# importer accepts these seven columns with these exact spellings and casing.
HEADERS = ['Title', 'Media URL', 'Pinterest Board', 'Description', 'Link', 'Publish Date', 'Keywords']
FIELDS = {'title', 'description', 'keywords', 'reviewed', 'source_url', 'source_checked_at', 'image_path', 'media_url', 'remote_file_id', 'short_url', 'short_link_id', 'media_verified_at', 'link_verified_at'}


class BatchError(ValueError):
    pass


def utc_now():
    return datetime.now(timezone.utc)


def next_half_hour(value):
    boundary = value.replace(minute=(value.minute // 30) * 30, second=0, microsecond=0)
    if boundary < value:
        boundary += timedelta(minutes=30)
    return boundary


def timestamp():
    return utc_now().isoformat().replace('+00:00', 'Z')


def https_url(value):
    if not isinstance(value, str) or re.search(r'\s|[<>"\\]', value):
        return False
    try:
        parsed = urlsplit(value)
        return parsed.scheme == 'https' and bool(parsed.hostname) and not parsed.username and not parsed.password and parsed.port in (None, 443)
    except ValueError:
        return False


def parse_approved_urls(path=DEFAULT_APPROVED):
    content = Path(path).read_text(encoding='utf-8-sig')
    content = re.sub(r'<!--.*?-->', '', content, flags=re.S)
    urls = []
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        match = re.fullmatch(r'[-*+] (https://\S+)', line)
        if not match or not https_url(match[1]) or urlsplit(match[1]).netloc not in VENDORS or '#' in match[1]:
            raise BatchError('Approved URL file contains invalid content or an unmapped host')
        if match[1] in urls:
            raise BatchError('Approved URL file contains a duplicate URL')
        urls.append(match[1])
    if not urls:
        raise BatchError('Approved URL file is empty')
    return urls


@contextmanager
def batch_lock(directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    lock = directory / '.lock'
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise BatchError(f'Batch lock exists: {lock}. Confirm no process is using this batch, inspect its manifest, then manually remove the lock; locks are never auto-deleted.') from None
    try:
        with os.fdopen(fd, 'w') as stream:
            stream.write(json.dumps({'pid': os.getpid(), 'created_at': timestamp()}))
        yield
    finally:
        lock.unlink()


def save_manifest(directory, manifest):
    target = Path(directory) / 'manifest.json'
    temporary = target.with_suffix('.json.tmp')
    with temporary.open('w', encoding='utf-8') as stream:
        json.dump(manifest, stream, indent=2, ensure_ascii=False)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, target)


def load_manifest(batch_dir):
    try:
        return json.loads((Path(batch_dir) / 'manifest.json').read_text(encoding='utf-8'))
    except json.JSONDecodeError:
        raise BatchError('Malformed manifest; restore a valid manifest or reconcile this batch before continuing') from None


def check_approval(manifest, approved_path):
    current = set(parse_approved_urls(approved_path))
    if any(url not in current for url in manifest['approved_urls']):
        raise BatchError('A batch URL was revoked. Restore authorization or create a new batch; existing slots are retained.')


def init_batch(batch_id, batches_root='batches', approved_path=DEFAULT_APPROVED, pilot=False):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,79}', batch_id):
        raise BatchError('Batch ID must contain only letters, numbers, underscore or hyphen')
    urls = parse_approved_urls(approved_path)
    if pilot:
        urls = [u for u in urls if urlsplit(u).hostname == 'try.elevenlabs.io']
    if not urls:
        raise BatchError('No approved URLs match the batch mode')
    directory = Path(batches_root) / batch_id
    with batch_lock(directory):
        if (directory / 'manifest.json').exists():
            manifest = load_manifest(directory)
            if manifest['mode'] != ('pilot' if pilot else 'full'):
                raise BatchError('Existing batch mode differs; use a new batch ID')
            check_approval(manifest, approved_path)
            return manifest
        queues = {}
        for url in urls:
            vendor, board = VENDORS[urlsplit(url).hostname]
            url_id = hashlib.sha256(url.encode()).hexdigest()[:12]
            slug = re.sub(r'[^a-z0-9]+', '-', vendor.lower()).strip('-')
            for slot in range(1, 11):
                queues.setdefault(vendor, []).append({'pin_id': f'{url_id}-{slot:02d}', 'url_id': url_id, 'affiliate_url': url, 'vendor': vendor, 'board': board, 'slot': slot, 'kind': 'guide' if slot <= 5 else 'promotion', 'imagekit_folder': f'/pinterest/{batch_id}/{slug}-{url_id}/', 'image_filename': f'pin-{slot:02d}.png'})
        pins = []
        while any(queues.values()):
            candidates = [v for v, q in queues.items() if q and (not pins or v != pins[-1]['vendor'])]
            if not candidates:
                candidates = [v for v, q in queues.items() if q]
            vendor = max(candidates, key=lambda v: len(queues[v]))
            pins.append(queues[vendor].pop(0))
        manifest = {'schema_version': 1, 'batch_id': batch_id, 'mode': 'pilot' if pilot else 'full', 'created_at': timestamp(), 'state': 'active', 'approved_urls': urls, 'pins': pins, 'exports': []}
        save_manifest(directory, manifest)
        return manifest


def validate_data(batch_dir, data):
    if not isinstance(data, dict) or set(data) - FIELDS:
        raise BatchError('Record contains unknown fields')
    for key, value in data.items():
        if key == 'reviewed':
            valid = type(value) is bool
        elif key == 'keywords':
            valid = isinstance(value, list) and bool(value) and all(isinstance(v, str) and v.strip() for v in value)
        else:
            valid = isinstance(value, str) and bool(value.strip())
        if not valid:
            raise BatchError(f'Invalid {key}')
        if key in ('title', 'description') and len(value) > (100 if key == 'title' else 500):
            raise BatchError(f'{key} exceeds Pinterest character limit')
        if key in ('source_url', 'media_url', 'short_url') and not https_url(value):
            raise BatchError(f'{key} must be HTTPS')
        if key == 'short_url':
            try:
                check_short_url(value)
            except ServiceError as exc:
                raise BatchError(str(exc)) from None
        if key.endswith('_at'):
            try:
                parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
                if parsed.tzinfo is None:
                    raise ValueError()
            except ValueError:
                raise BatchError(f'{key} must include a timezone') from None
        if key == 'image_path':
            path = (Path(batch_dir) / value).resolve()
            if not path.is_relative_to(Path(batch_dir).resolve()) or not path.is_file():
                raise BatchError('image_path must be an existing file inside this batch directory')


def record_pin(batch_dir, pin_id, data, approved_path=DEFAULT_APPROVED):
    with batch_lock(batch_dir):
        manifest = load_manifest(batch_dir)
        if manifest['state'] in ('uploaded', 'blocked'):
            raise BatchError('Batch is uploaded or blocked; explicit reconciliation is required')
        check_approval(manifest, approved_path)
        validate_data(batch_dir, data)
        pin = next((p for p in manifest['pins'] if p['pin_id'] == pin_id), None)
        if pin is None:
            raise BatchError('Unknown pin ID')
        if 'short_url' in data and data['short_url'] != pin.get('short_url'):
            try:
                check_short_url(data['short_url'], allow_legacy=False)
            except ServiceError:
                raise BatchError('New short URLs must use justonemedia.short.gy') from None
        data = dict(data)
        changed = {k for k in data if data[k] != pin.get(k)}
        for source_fields, evidence in (({'media_url', 'image_path'}, 'media_verified_at'), ({'short_url'}, 'link_verified_at')):
            if changed & source_fields:
                pin.pop(evidence, None)
                data.pop(evidence, None)
        review_fields = {'title', 'description', 'keywords', 'image_path', 'media_url', 'short_url'}
        if 'reviewed' not in data and any(k in data and data[k] != pin.get(k) for k in review_fields):
            pin['reviewed'] = False
        pin.update(data)
        if changed and manifest['state'] == 'exported':
            manifest['state'] = 'active'
            for export in manifest['exports']:
                export['invalidated'] = True
        save_manifest(batch_dir, manifest)
        return manifest


def complete_pin(batch_dir, pin, *, require_verification=True):
    fields = FIELDS if require_verification else FIELDS - {'media_verified_at', 'link_verified_at'}
    if not fields.issubset(pin) or pin.get('reviewed') is not True:
        return False
    try:
        validate_data(batch_dir, {k: pin[k] for k in fields})
    except BatchError:
        return False
    return bool(re.search(r'\baffiliate\b|\bcommission\b|#ad\b', pin['description'], re.I))


def validate_pin_plan(manifest):
    recovery = 'Malformed pin plan; restore a valid manifest or reconcile this batch before continuing'
    if not isinstance(manifest, dict):
        raise BatchError(recovery)
    if not isinstance(manifest.get('batch_id'), str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,79}', manifest['batch_id']) or manifest.get('state') not in ('active', 'exported', 'blocked', 'uploaded'):
        raise BatchError(recovery)
    if not isinstance(manifest.get('exports'), list) or any(not isinstance(e, dict) for e in manifest['exports']):
        raise BatchError(recovery)
    if not isinstance(manifest.get('approved_urls'), list) or not all(https_url(url) for url in manifest['approved_urls']) or not isinstance(manifest.get('pins'), list):
        raise BatchError(recovery)
    urls = manifest['approved_urls']
    pins = manifest['pins']
    for pin in pins:
        if not isinstance(pin, dict) or any(not isinstance(pin.get(field), str) or not pin[field].strip() for field in ('pin_id', 'affiliate_url', 'board', 'kind')) or type(pin.get('slot')) is not int:
            raise BatchError(recovery)
        for field in FIELDS & pin.keys():
            value = pin[field]
            if field == 'reviewed':
                valid = type(value) is bool
            elif field == 'keywords':
                valid = isinstance(value, list) and bool(value) and all(isinstance(v, str) and v.strip() for v in value)
            else:
                valid = isinstance(value, str) and bool(value.strip())
            if not valid:
                raise BatchError(recovery)
    if not urls or len(set(urls)) != len(urls) or any(p['affiliate_url'] not in urls for p in pins):
        raise BatchError('Pin plan differs from approved URLs')
    if len({p['pin_id'] for p in pins}) != len(pins):
        raise BatchError('Duplicate pin IDs')
    for url in urls:
        group = [p for p in pins if p['affiliate_url'] == url]
        if len(group) != 10 or {p['slot'] for p in group} != set(range(1, 11)) or any(p['kind'] != ('guide' if p['slot'] <= 5 else 'promotion') for p in group):
            raise BatchError('Each approved URL requires exactly five guide and five promotion slots')
        for field in ('title', 'description', 'image_path', 'media_url', 'remote_file_id'):
            values = [p[field] for p in group if field in p]
            if field in ('title', 'description'):
                values = [' '.join(value.split()).casefold() for value in values]
            if len(set(values)) != len(values):
                raise BatchError(f'Each approved URL requires distinct {field} values')
    short_urls = [p['short_url'] for p in pins if p.get('short_url')]
    if len(set(short_urls)) != len(short_urls):
        raise BatchError('Duplicate short_url values; each pin requires its own link')


def pending_pins(batch_dir):
    manifest = load_manifest(batch_dir)
    validate_pin_plan(manifest)
    if manifest['state'] != 'active':
        return []
    return [p for p in manifest['pins'] if not complete_pin(batch_dir, p)]


def export_batch(batch_dir, approved_path=DEFAULT_APPROVED, now=None, verify_pins=None):
    if verify_pins is None:
        raise BatchError('Live verification is required; use pinterest_export.py')
    with batch_lock(batch_dir):
        manifest = load_manifest(batch_dir)
        validate_pin_plan(manifest)
        if manifest['state'] in ('uploaded', 'blocked'):
            raise BatchError('Batch is uploaded or blocked; explicit reconciliation is required')
        check_approval(manifest, approved_path)
        incomplete = [p['pin_id'] for p in manifest['pins'] if not complete_pin(batch_dir, p, require_verification=False)]
        if incomplete:
            raise BatchError(f'{len(incomplete)} planned pins are incomplete; no CSV was generated')
        if verify_pins is not None:
            try:
                verify_pins(manifest, Path(batch_dir))
                check_approval(manifest, approved_path)
                validate_pin_plan(manifest)
                if not all(complete_pin(batch_dir, pin) for pin in manifest['pins']):
                    raise BatchError('Live verification left incomplete pins; no CSV was generated')
            except (ValueError, OSError):
                manifest.update(state='blocked', blocked_reason='Live export verification failed; see reported error')
                for export in manifest['exports']:
                    export['invalidated'] = True
                save_manifest(batch_dir, manifest)
                raise
        now = now or utc_now()
        if now.tzinfo is None:
            raise BatchError('Export time requires a timezone')
        now = now.astimezone(timezone.utc)
        first_publish = next_half_hour(now + timedelta(minutes=30))
        version = len(manifest['exports']) + 1
        path = Path(batch_dir) / f'pinterest-{manifest["batch_id"]}-v{version:03d}.csv'
        while path.exists():
            version += 1
            path = Path(batch_dir) / f'pinterest-{manifest["batch_id"]}-v{version:03d}.csv'
        temporary = path.with_suffix('.csv.tmp')
        with temporary.open('w', encoding='utf-8', newline='') as stream:
            writer = csv.writer(stream)
            writer.writerow(HEADERS)
            for n, p in enumerate(manifest['pins']):
                date = (first_publish + timedelta(minutes=30*n)).strftime('%Y-%m-%dT%H:%M:%S')
                writer.writerow([p['title'], p['media_url'], p['board'], p['description'], p['short_url'], date, ', '.join(p['keywords'])])
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        result = {'path': str(path.resolve()), 'version': version, 'exported_at': now.isoformat(), 'rows': len(manifest['pins']), 'age_seconds': 0, 'scheduling_timezone': 'UTC'}
        manifest['exports'].append(result)
        manifest['state'] = 'exported'
        save_manifest(batch_dir, manifest)
        return result


def mark_uploaded(batch_dir):
    with batch_lock(batch_dir):
        manifest = load_manifest(batch_dir)
        if manifest['state'] != 'exported' or not manifest['exports'] or manifest['exports'][-1].get('invalidated'):
            raise BatchError('Only an exported batch can be marked uploaded')
        manifest.update(state='uploaded', uploaded_at=timestamp())
        save_manifest(batch_dir, manifest)
        return manifest


def block_batch(batch_dir, reason):
    if not isinstance(reason, str) or not reason.strip():
        raise BatchError('A blocking reason is required')
    with batch_lock(batch_dir):
        manifest = load_manifest(batch_dir)
        if manifest['state'] == 'uploaded':
            raise BatchError('Uploaded batches cannot be blocked or resumed; explicit reconciliation is required')
        manifest.update(state='blocked', blocked_reason=reason)
        save_manifest(batch_dir, manifest)
        return manifest


def resume_batch(batch_dir, approved_path=DEFAULT_APPROVED):
    with batch_lock(batch_dir):
        manifest = load_manifest(batch_dir)
        if manifest['state'] != 'blocked':
            raise BatchError('Only a blocked batch can be resumed')
        check_approval(manifest, approved_path)
        manifest['state'] = 'active'
        manifest.pop('blocked_reason', None)
        for export in manifest['exports']:
            export['invalidated'] = True
        save_manifest(batch_dir, manifest)
        return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--approved-file', default=str(DEFAULT_APPROVED))
    parser.add_argument('--batches-root', default='batches')
    commands = parser.add_subparsers(dest='command', required=True)
    for name in ('init', 'status', 'pending', 'record', 'export', 'mark-uploaded', 'block', 'resume'):
        command = commands.add_parser(name)
        command.add_argument('--batch', required=True)
        if name == 'init':
            command.add_argument('--pilot', action='store_true')
        if name == 'record':
            command.add_argument('--pin', required=True)
            command.add_argument('--data', required=True)
        if name == 'block':
            command.add_argument('--reason', required=True)
    args = parser.parse_args(argv)
    try:
        directory = Path(args.batches_root) / args.batch
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,79}', args.batch):
            raise BatchError('Invalid batch ID')
        if args.command == 'init':
            manifest = init_batch(args.batch, args.batches_root, args.approved_file, args.pilot)
            result = {'batch_id': manifest['batch_id'], 'state': manifest['state'], 'pins': len(manifest['pins'])}
        elif args.command == 'pending':
            result = pending_pins(directory)
        elif args.command == 'export':
            raise BatchError('Use pinterest_export.py for live-verified CSV export')
        elif args.command == 'record':
            record_pin(directory, args.pin, json.loads(Path(args.data).read_text(encoding='utf-8-sig')), args.approved_file)
            result = {'recorded': args.pin}
        elif args.command == 'mark-uploaded':
            result = {'state': mark_uploaded(directory)['state']}
        elif args.command == 'block':
            result = {'state': block_batch(directory, args.reason)['state']}
        elif args.command == 'resume':
            result = {'state': resume_batch(directory, args.approved_file)['state']}
        else:
            manifest = load_manifest(directory)
            try:
                validate_pin_plan(manifest)
                complete = sum(complete_pin(directory, p) for p in manifest['pins'])
            except BatchError:
                complete = 0
            exports = [dict(e, age_seconds=max(0, int((utc_now() - datetime.fromisoformat(e['exported_at'])).total_seconds()))) for e in manifest['exports']]
            result = {'batch_id': manifest['batch_id'], 'state': manifest['state'], 'planned': len(manifest['pins']), 'complete': complete, 'exports': exports}
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (BatchError, OSError, ValueError, KeyError) as exc:
        message = str(exc) if isinstance(exc, BatchError) else 'File or data operation failed; check paths, permissions and JSON structure'
        print(json.dumps({'error': message}), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
