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
from zoneinfo import ZoneInfo

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
# This campaign deliberately contains ten products. Approved vendors outside
# this map remain available to other campaign configurations.
CAMPAIGN_PRODUCTS = {
    'Carepatron': {'primary_url': 'https://get.carepatron.com/michaelmedium', 'eligible_boards': ['Productivity & Efficiency']},
    'DataHawk': {'primary_url': 'https://get.datahawk.co/mau0otko9lz4-o5aq3q', 'eligible_boards': ['Business Growth Strategies']},
    'ElevenLabs': {'primary_url': 'https://try.elevenlabs.io/izj2b165mcsj', 'eligible_boards': ['AI Tools & Automation']},
    'AdCreative.ai': {'primary_url': 'https://free-trial.adcreative.ai/8phdnllve4xi', 'eligible_boards': ['AI Tools & Automation']},
    'Snowfire': {'primary_url': 'https://partners.snowfire.ai/j1a8kovs1uez', 'eligible_boards': ['Business & Entrepreneurship']},
    'Moosend': {'primary_url': 'https://trymoo.moosend.com/michaelmedium', 'eligible_boards': ['Business Growth Strategies']},
    'GetResponse': {'primary_url': 'https://try.getresponsetoday.com/smypvzu98eko-kfze15', 'eligible_boards': ['Business Growth Strategies']},
    'Flippa': {'primary_url': 'https://referral.flippa.com/vettedsaasblueprint', 'eligible_boards': ['Business & Entrepreneurship']},
    'Glide': {'primary_url': 'https://join.glideapps.com/9r1tcciij70r', 'eligible_boards': ['AI Tools & Automation']},
    'Manychat': {'primary_url': 'https://manychat.partnerlinks.io/vettedsaasblueprint', 'eligible_boards': ['Business Growth Strategies']},
}
# Keep this in sync with the proven Pinterest bulk-upload template. Pinterest's
# importer accepts these seven columns with these exact spellings and casing.
HEADERS = ['Title', 'Media URL', 'Pinterest Board', 'Description', 'Link', 'Publish Date', 'Keywords']
FIELDS = {'title', 'description', 'keywords', 'reviewed', 'source_url', 'source_checked_at', 'image_path', 'media_url', 'remote_file_id', 'short_url', 'short_link_id', 'media_verified_at', 'link_verified_at', 'creative_plan', 'review_evidence', 'board', 'destination_url'}
OPTIONAL_FIELDS = {'source_sha256'}
SCHEMA_VERSION = 2
DEFAULT_BATCH_SIZE = 100
SCHEDULING_TIMEZONE = ZoneInfo('Africa/Johannesburg')
SCHEDULE_START_HOUR = 9
SCHEDULE_END_MINUTE = 18 * 60 + 30
SCHEDULE_SLOTS_PER_DAY = 20
INFRASTRUCTURE_DIRECTORIES = {'.schedule-lock'}
CREATIVE_FINGERPRINT_FIELDS = ('title', 'description', 'visual_concept', 'asset_sha256')


class BatchError(ValueError):
    pass


def utc_now():
    return datetime.now(timezone.utc)


def next_half_hour(value):
    boundary = value.replace(minute=(value.minute // 30) * 30, second=0, microsecond=0)
    if boundary < value:
        boundary += timedelta(minutes=30)
    return boundary


def _ceil_schedule_slot(value):
    """Return the first local half-hour slot at or after an aware datetime."""
    value = value.astimezone(SCHEDULING_TIMEZONE)
    boundary = value.replace(minute=(value.minute // 30) * 30, second=0, microsecond=0)
    if boundary < value:
        boundary += timedelta(minutes=30)
    opening = boundary.replace(hour=SCHEDULE_START_HOUR, minute=0)
    if boundary < opening:
        return opening
    if boundary.hour * 60 + boundary.minute > SCHEDULE_END_MINUTE:
        return (boundary + timedelta(days=1)).replace(hour=SCHEDULE_START_HOUR, minute=0)
    return boundary


def _next_schedule_slot(value):
    value += timedelta(minutes=30)
    if value.hour * 60 + value.minute > SCHEDULE_END_MINUTE:
        return (value + timedelta(days=1)).replace(hour=SCHEDULE_START_HOUR, minute=0)
    return value


def _reserved_schedule_slots(batches_root):
    """Collect slots held or consumed by every export recorded by this app."""
    occupied = set()
    root = Path(batches_root)
    if not root.exists():
        return occupied
    for directory in root.iterdir():
        if directory.name in INFRASTRUCTURE_DIRECTORIES:
            continue
        if not directory.is_dir():
            continue
        manifest_path = directory / 'manifest.json'
        if not manifest_path.exists():
            raise BatchError(f'Unreadable batch history at {manifest_path}; schedule safety cannot be established')
        try:
            manifest = load_manifest(directory)
        except (BatchError, OSError) as exc:
            raise BatchError(f'Unreadable batch history at {manifest_path}; schedule safety cannot be established') from exc
        for reservation in manifest.get('reservations', []):
            # A cancelled whole export releases its slots. Older manifests use
            # lowercase lifecycle values; keep them readable during migration.
            if str(reservation.get('status', '')).upper() in {'CANCELLED', 'FAILED'}:
                continue
            slots = reservation.get('schedule_slots', reservation.get('slots', []))
            if not isinstance(slots, list):
                raise BatchError(f'Malformed schedule history at {manifest_path}')
            for slot in slots:
                if isinstance(slot, str):
                    occupied.add(slot)
        if manifest.get('schema_version', 1) < SCHEMA_VERSION:
            for export in manifest.get('exports', []):
                path = export.get('path')
                if not isinstance(path, str):
                    raise BatchError(f'Missing legacy export path at {manifest_path}')
                csv_path = Path(path)
                if not csv_path.is_absolute():
                    csv_path = directory / csv_path
                try:
                    with csv_path.open(newline='', encoding='utf-8') as stream:
                        for row in csv.DictReader(stream):
                            slot = row.get('Publish Date')
                            if not isinstance(slot, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}', slot):
                                raise BatchError(f'Malformed legacy schedule history at {csv_path}')
                            occupied.add(slot)
                except (OSError, csv.Error) as exc:
                    raise BatchError(f'Unreadable legacy schedule history at {csv_path}') from exc
    return occupied


def plan_schedule_slots(anchor, count, batches_root):
    """Allocate free weekday-independent Johannesburg half-hour slots."""
    if count <= 0:
        return []
    candidate = _ceil_schedule_slot(anchor + timedelta(minutes=30))
    occupied = _reserved_schedule_slots(batches_root)
    slots = []
    while len(slots) < count:
        key = candidate.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S')
        if key not in occupied:
            slots.append(key)
            occupied.add(key)
        candidate = _next_schedule_slot(candidate)
    return slots


def weave_export_pins(pins):
    """Best-effort guide/promotion weaving while preserving per-kind order."""
    guides = [pin for pin in pins if pin.get('kind') == 'guide']
    promotions = [pin for pin in pins if pin.get('kind') == 'promotion']
    if not guides or not promotions:
        return list(pins)
    first_kind = 'guide' if len(guides) > len(promotions) else 'promotion'
    if len(guides) == len(promotions):
        first_kind = pins[0].get('kind')
    queues = {'guide': guides, 'promotion': promotions}
    ordered = []
    kind = first_kind
    while queues['guide'] or queues['promotion']:
        if not queues[kind]:
            kind = 'promotion' if kind == 'guide' else 'guide'
        ordered.append(queues[kind].pop(0))
        kind = 'promotion' if kind == 'guide' else 'guide'
    return ordered


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
        manifest = json.loads((Path(batch_dir) / 'manifest.json').read_text(encoding='utf-8'))
    except json.JSONDecodeError:
        raise BatchError('Malformed manifest; restore a valid manifest or reconcile this batch before continuing') from None
    if not isinstance(manifest, dict):
        raise BatchError('Malformed manifest; restore a valid manifest or reconcile this batch before continuing')
    return manifest


def migrate_manifest(manifest):
    migrated = dict(manifest)
    migrated['schema_version'] = SCHEMA_VERSION
    migrated.setdefault('batch_size', len(migrated.get('pins', [])))
    migrated.setdefault('image_attempt_budget', (migrated['batch_size'] * 6 + 4) // 5)
    migrated.setdefault('image_attempts', 0)
    migrated.setdefault('reservations', [])
    migrated.setdefault('outcome', None)
    migrated.setdefault('primary_destinations', {})
    migrated['legacy_plan'] = True
    for pin in migrated.get('pins', []):
        pin.setdefault('product', pin.get('vendor'))
        pin.setdefault('destination_url', pin.get('affiliate_url'))
        pin.setdefault('eligible_boards', [pin.get('board')])
        pin.setdefault('creative_plan', {'kind': pin.get('kind'), 'slot': pin.get('slot')})
        pin.setdefault('attempts', 0)
        pin.setdefault('repair_attempts', 0)
        pin.setdefault('failed_attempts', 0)
        pin.setdefault('failed_repairs', 0)
    return migrated


def migrate_legacy_batch(batch_dir, approved_path=DEFAULT_APPROVED):
    with batch_lock(batch_dir):
        manifest = load_manifest(batch_dir)
        if manifest.get('schema_version', 1) >= SCHEMA_VERSION:
            return manifest
        if manifest.get('state') != 'active' or manifest.get('exports'):
            raise BatchError('Only unfinished legacy batches can be migrated; exported batches remain read-only')
        check_approval(manifest, approved_path)
        snapshot = Path(batch_dir) / 'manifest.v1.snapshot.json'
        if not snapshot.exists():
            snapshot.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding='utf-8')
        migrated = migrate_manifest(manifest)
        save_manifest(batch_dir, migrated)
        return migrated


def check_approval(manifest, approved_path):
    current = set(parse_approved_urls(approved_path))
    if any(url not in current for url in manifest['approved_urls']):
        raise BatchError('A batch URL was revoked. Restore authorization or create a new batch; existing slots are retained.')


def normalized_fingerprint(pin, batch_dir):
    plan = pin.get('creative_plan') if isinstance(pin.get('creative_plan'), dict) else {}
    values = {
        'title': pin.get('title'),
        'description': pin.get('description'),
        'visual_concept': plan.get('visual_concept'),
    }
    fingerprint = {}
    for field, value in values.items():
        if isinstance(value, str) and value.strip():
            fingerprint[field] = ' '.join(value.split()).casefold()
    image_path = pin.get('image_path')
    if isinstance(image_path, str):
        try:
            fingerprint['asset_sha256'] = hashlib.sha256((Path(batch_dir) / image_path).read_bytes()).hexdigest()
        except OSError as exc:
            raise BatchError(f'Unable to read asset history for {pin.get("pin_id", "unknown pin")}') from exc
    return fingerprint


def load_creative_history(batches_root, current_batch_id):
    """Read sibling manifests as exact-match duplicate history; fail closed on unreadable history."""
    root = Path(batches_root)
    history_batches = []
    manifests = []
    fingerprints = []
    if not root.exists():
        return history_batches, manifests, fingerprints
    try:
        siblings = sorted(path for path in root.iterdir() if path.is_dir() and path.name not in {current_batch_id, *INFRASTRUCTURE_DIRECTORIES})
    except OSError as exc:
        raise BatchError('Unable to read batch history; duplicate safety cannot be established') from exc
    for sibling in siblings:
        manifest_path = sibling / 'manifest.json'
        if not manifest_path.exists():
            raise BatchError(f'Unreadable batch history at {manifest_path}; duplicate safety cannot be established')
        try:
            prior = load_manifest(sibling)
            pins = prior.get('pins')
            if not isinstance(pins, list):
                raise BatchError('Malformed history pin list')
        except (BatchError, OSError, TypeError) as exc:
            raise BatchError(f'Unreadable batch history at {manifest_path}; duplicate safety cannot be established') from exc
        history_batches.append(prior.get('batch_id', sibling.name))
        manifests.append(prior)
        for pin in pins:
            if not isinstance(pin, dict):
                raise BatchError(f'Malformed pin in batch history at {manifest_path}')
            fingerprint = normalized_fingerprint(pin, sibling)
            if fingerprint:
                fingerprints.append({'batch_id': prior.get('batch_id', sibling.name), 'pin_id': pin.get('pin_id'), 'values': fingerprint})
    return history_batches, manifests, fingerprints


def assert_no_creative_duplicates(manifest, pin_id, pin, batch_dir):
    candidate = normalized_fingerprint(pin, batch_dir)
    for previous in manifest.get('prior_creative_fingerprints', []):
        values = previous.get('values', {})
        for field in CREATIVE_FINGERPRINT_FIELDS:
            if candidate.get(field) and candidate[field] == values.get(field):
                raise BatchError(f'Duplicate {field} from prior batch {previous.get("batch_id")}')
    for other in manifest.get('pins', []):
        if other.get('pin_id') == pin_id:
            continue
        values = normalized_fingerprint(other, batch_dir)
        for field in CREATIVE_FINGERPRINT_FIELDS:
            if candidate.get(field) and candidate[field] == values.get(field):
                raise BatchError(f'Duplicate {field} in current batch')


def init_batch(batch_id, batches_root='batches', approved_path=DEFAULT_APPROVED, pilot=False, batch_size=DEFAULT_BATCH_SIZE, campaign=None, allocation_cursor=None, board_history=None):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,79}', batch_id):
        raise BatchError('Batch ID must contain only letters, numbers, underscore or hyphen')
    if type(batch_size) is not int or batch_size <= 0:
        raise BatchError('Batch size must be a positive integer')
    if allocation_cursor is not None and (type(allocation_cursor) is not int or allocation_cursor < 0):
        raise BatchError('Allocation cursor must be a non-negative integer')
    urls = parse_approved_urls(approved_path)
    campaign = campaign or CAMPAIGN_PRODUCTS
    if not isinstance(campaign, dict) or not campaign:
        raise BatchError('Campaign requires at least one configured product')
    selected = list(campaign.items())
    if pilot:
        selected = [(name, config) for name, config in selected if name == 'ElevenLabs']
        batch_size = min(batch_size, 10)
    if not selected and batch_size:
        raise BatchError('No configured products match the batch mode')
    directory = Path(batches_root) / batch_id
    with batch_lock(directory):
        if (directory / 'manifest.json').exists():
            manifest = load_manifest(directory)
            if manifest['mode'] != ('pilot' if pilot else 'full'):
                raise BatchError('Existing batch mode differs; use a new batch ID')
            if manifest.get('batch_size', len(manifest['pins'])) != batch_size:
                raise BatchError('Existing batch size differs; use a new batch ID')
            check_approval(manifest, approved_path)
            return manifest
        history_batches, history_manifests, prior_fingerprints = load_creative_history(batches_root, batch_id)
        schema_v2_history = [item for item in history_manifests if item.get('schema_version', 1) >= SCHEMA_VERSION]
        if allocation_cursor is None:
            allocation_cursor = max((item.get('allocation_cursor', 0) for item in schema_v2_history), default=0)
        if board_history is None and schema_v2_history:
            latest = max(schema_v2_history, key=lambda item: item.get('created_at', ''))
            board_history = latest.get('board_history', {})
        quotient, remainder = divmod(batch_size, len(selected)) if selected else (0, 0)
        allocations = {name: quotient for name, _ in selected}
        for offset in range(remainder):
            allocations[selected[(allocation_cursor + offset) % len(selected)][0]] += 1
        guide_counts = {name: count // 2 for name, count in allocations.items()}
        extra_guides = (batch_size + 1) // 2 - sum(guide_counts.values())
        for offset in range(len(selected)):
            product = selected[(allocation_cursor + offset) % len(selected)][0]
            if extra_guides and allocations[product] % 2:
                guide_counts[product] += 1
                extra_guides -= 1
        approved_set = set(urls)
        primary_destinations = {}
        queues = {}
        board_counts = dict(board_history or {})
        for product_index, (product, config) in enumerate(selected):
            if not isinstance(config, dict) or not isinstance(config.get('primary_url'), str) or not isinstance(config.get('eligible_boards'), list) or not config['eligible_boards'] or not all(isinstance(board, str) and board.strip() for board in config['eligible_boards']):
                raise BatchError(f'Invalid campaign configuration for {product}')
            primary_url = config['primary_url']
            host = urlsplit(primary_url).hostname
            if primary_url not in approved_set or host not in VENDORS or VENDORS[host][0].casefold() != product.casefold():
                if allocations[product]:
                    raise BatchError(f'Configured primary destination for {product} is not allowlisted')
                primary_url = None
            primary_destinations[product] = primary_url
            count = allocations[product]
            boards = config['eligible_boards']
            slug = re.sub(r'[^a-z0-9]+', '-', product.lower()).strip('-')
            queues[product] = []
            guide_count = guide_counts[product]
            for slot in range(1, count + 1):
                kind = 'guide' if slot <= guide_count else 'promotion'
                pin_id = hashlib.sha256(f'{batch_id}|{product.casefold()}|{slot}'.encode()).hexdigest()[:16]
                min_count = min(board_counts.get(name, 0) for name in boards)
                candidates = [name for name in boards if board_counts.get(name, 0) == min_count]
                board = candidates[(allocation_cursor + product_index + slot - 1) % len(candidates)]
                board_counts[board] = board_counts.get(board, 0) + 1
                queues[product].append({'pin_id': pin_id, 'product': product, 'vendor': product, 'url_id': hashlib.sha256(product.casefold().encode()).hexdigest()[:12], 'affiliate_url': primary_url, 'destination_url': primary_url, 'board': board, 'eligible_boards': list(boards), 'slot': slot, 'kind': kind, 'imagekit_folder': f'/pinterest/{batch_id}/{slug}/', 'image_filename': f'pin-{slot:02d}.png', 'attempts': 0, 'repair_attempts': 0, 'failed_attempts': 0, 'failed_repairs': 0})
        pins = []
        next_product = 0
        product_indices = {product: index for index, (product, _) in enumerate(selected)}
        total_pins = sum(allocations.values())
        for row in range(total_pins):
            desired_kind = 'guide' if row % 2 == 0 else 'promotion'
            for offset in range(len(selected)):
                product = selected[(next_product + offset) % len(selected)][0]
                candidate = next((pin for pin in queues[product] if pin['kind'] == desired_kind), None)
                if candidate is not None:
                    queues[product].remove(candidate)
                    pins.append(candidate)
                    next_product = (product_indices[product] + 1) % len(selected)
                    break
            else:
                raise BatchError('Unable to preserve alternating guide and promotion output order')
        used_urls = list(dict.fromkeys(primary_destinations[name] for name, count in allocations.items() if count))
        manifest = {'schema_version': SCHEMA_VERSION, 'batch_id': batch_id, 'mode': 'pilot' if pilot else 'full', 'batch_size': len(pins), 'image_attempt_budget': (len(pins) * 6 + 4) // 5, 'image_attempts': 0, 'allocation_cursor': allocation_cursor + 1, 'board_history': board_counts, 'history_batches': history_batches, 'prior_creative_fingerprints': prior_fingerprints, 'created_at': timestamp(), 'state': 'active', 'approved_urls': used_urls, 'primary_destinations': primary_destinations, 'pins': pins, 'exports': [], 'reservations': [], 'outcome': None}
        save_manifest(directory, manifest)
        return manifest


def validate_data(batch_dir, data):
    if not isinstance(data, dict) or set(data) - FIELDS - OPTIONAL_FIELDS:
        raise BatchError('Record contains unknown fields')
    for key, value in data.items():
        if key == 'reviewed':
            valid = type(value) is bool
        elif key == 'keywords':
            valid = isinstance(value, list) and bool(value) and all(isinstance(v, str) and v.strip() for v in value)
        elif key in ('creative_plan', 'review_evidence'):
            valid = isinstance(value, dict) and bool(value)
            if valid and key == 'creative_plan':
                required = {'audience_problem', 'search_intent', 'supported_promise', 'hook', 'visual_concept', 'evidence'}
                valid = required.issubset(value) and all(isinstance(value[field], str) and value[field].strip() for field in required)
                if valid:
                    valid = https_url(value['evidence'])
            if valid and key == 'review_evidence':
                required = {'verdict', 'content_hash', 'board_hash', 'destination_hash', 'asset_sha256', 'reviewer', 'reviewed_at'}
                valid = required.issubset(value) and value.get('verdict') == 'PASS' and all(isinstance(value[field], str) and value[field].strip() for field in required)
                if valid:
                    try:
                        reviewed_at = datetime.fromisoformat(value['reviewed_at'].replace('Z', '+00:00'))
                        valid = reviewed_at.tzinfo is not None
                    except ValueError:
                        valid = False
        else:
            valid = isinstance(value, str) and bool(value.strip())
        if not valid:
            raise BatchError(f'Invalid {key}')
        if key == 'source_sha256' and not re.fullmatch(r'[a-fA-F0-9]{64}', value):
            raise BatchError('source_sha256 must be a SHA-256 hex digest')
        if key in ('title', 'description') and len(value) > (100 if key == 'title' else 500):
            raise BatchError(f'{key} exceeds Pinterest character limit')
        if key in ('source_url', 'media_url', 'short_url', 'destination_url') and not https_url(value):
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
        if manifest.get('schema_version', 1) < SCHEMA_VERSION:
            raise BatchError('Legacy batch requires explicit migration before edits')
        if manifest['state'] in ('uploaded', 'blocked'):
            raise BatchError('Batch is uploaded or blocked; explicit reconciliation is required')
        check_approval(manifest, approved_path)
        validate_data(batch_dir, data)
        pin = next((p for p in manifest['pins'] if p['pin_id'] == pin_id), None)
        if pin is None:
            raise BatchError('Unknown pin ID')
        if 'board' in data and data['board'] not in pin.get('eligible_boards', [pin['board']]):
            raise BatchError('Board is outside this pin’s eligible mapping')
        if 'destination_url' in data and data['destination_url'] != manifest.get('primary_destinations', {}).get(pin.get('product')):
            raise BatchError('Destination must remain the configured primary URL')
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
        review_fields = {'title', 'description', 'keywords', 'image_path', 'media_url', 'board', 'destination_url', 'creative_plan', 'source_url', 'source_checked_at', 'source_sha256'}
        if 'reviewed' not in data and any(k in data and data[k] != pin.get(k) for k in review_fields):
            pin['reviewed'] = False
            pin.pop('review_evidence', None)
        if data.get('reviewed') is True:
            reviewed_pin = dict(pin, **data)
            evidence = data.get('review_evidence', pin.get('review_evidence'))
            expected = review_hash(reviewed_pin, batch_dir)
            if not reviewed_pin.get('source_url') or not reviewed_pin.get('source_checked_at') or not creative_plan_complete(reviewed_pin.get('creative_plan')):
                raise BatchError('Source evidence and a complete creative plan are required before review')
            if not isinstance(evidence, dict) or evidence.get('content_hash') != expected or evidence.get('source_hash') != source_hash(reviewed_pin):
                raise BatchError('Review evidence does not match the pin content, board, destination and asset')
        candidate = dict(pin, **data)
        if manifest.get('schema_version', 1) >= SCHEMA_VERSION:
            assert_no_creative_duplicates(manifest, pin_id, candidate, batch_dir)
        if changed & review_fields and pin.get('outcome') == 'rejected':
            pin.pop('outcome', None)
        pin.update(data)
        if changed and manifest['state'] == 'exported':
            manifest['state'] = 'active'
            for export in manifest['exports']:
                export['invalidated'] = True
        save_manifest(batch_dir, manifest)
        return manifest


def complete_pin(batch_dir, pin, *, require_verification=True):
    legacy = pin.get('_legacy', False)
    fields = FIELDS if require_verification else FIELDS - {'media_verified_at', 'link_verified_at'}
    if legacy:
        fields = FIELDS - {'creative_plan', 'review_evidence', 'media_verified_at', 'link_verified_at'}
    if not fields.issubset(pin) or pin.get('reviewed') is not True or not legacy and not valid_review(pin, batch_dir):
        return False
    try:
        validate_data(batch_dir, {k: pin[k] for k in fields})
    except BatchError:
        return False
    return bool(re.search(r'\baffiliate\b|\bcommission\b|#ad\b', pin['description'], re.I))


def review_hash(pin, batch_dir):
    try:
        asset_sha256 = hashlib.sha256((Path(batch_dir) / pin['image_path']).read_bytes()).hexdigest()
    except (KeyError, OSError, TypeError):
        asset_sha256 = None
    payload = {
        'title': pin.get('title'), 'description': pin.get('description'), 'keywords': pin.get('keywords'),
        'creative_plan': pin.get('creative_plan'),
        'source_url': pin.get('source_url'), 'source_checked_at': pin.get('source_checked_at'),
        'source_sha256': pin.get('source_sha256'),
        'board': pin.get('board'), 'destination_url': pin.get('destination_url'),
        'media_url': pin.get('media_url'), 'remote_file_id': pin.get('remote_file_id'),
        'asset_sha256': asset_sha256,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def source_hash(pin):
    payload = {key: pin.get(key) for key in ('source_url', 'source_checked_at', 'source_sha256')}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def creative_plan_complete(plan):
    required = {'audience_problem', 'search_intent', 'supported_promise', 'hook', 'visual_concept', 'evidence'}
    return isinstance(plan, dict) and required.issubset(plan) and all(isinstance(plan[field], str) and plan[field].strip() for field in required) and https_url(plan['evidence'])


def review_evidence_payload(pin, batch_dir, reviewer, reviewed_at=None):
    asset_sha256 = hashlib.sha256((Path(batch_dir) / pin['image_path']).read_bytes()).hexdigest()
    hash_text = lambda value: hashlib.sha256(value.encode()).hexdigest()
    return {
        'verdict': 'PASS',
        'content_hash': review_hash(pin, batch_dir),
        'source_hash': source_hash(pin),
        'board_hash': hash_text(pin['board']),
        'destination_hash': hash_text(pin['destination_url']),
        'asset_sha256': asset_sha256,
        'reviewer': reviewer,
        'reviewed_at': reviewed_at or timestamp(),
    }


def valid_review(pin, batch_dir):
    evidence = pin.get('review_evidence')
    if not isinstance(evidence, dict):
        return False
    try:
        expected = review_evidence_payload(pin, batch_dir, evidence['reviewer'], evidence['reviewed_at'])
    except (KeyError, OSError, TypeError):
        return False
    return all(evidence.get(key) == expected[key] for key in ('verdict', 'content_hash', 'source_hash', 'board_hash', 'destination_hash', 'asset_sha256'))


def record_image_attempt(batch_dir, pin_id):
    """Persist a generation attempt before calling the image provider."""
    with batch_lock(batch_dir):
        manifest = load_manifest(batch_dir)
        pin = next((item for item in manifest['pins'] if item['pin_id'] == pin_id), None)
        if pin is None:
            raise BatchError('Unknown pin ID')
        if manifest.get('state') != 'active' or pin.get('outcome') in ('uploaded', 'omitted', 'rejected'):
            raise BatchError('Pin is closed to image attempts')
        if not creative_plan_complete(pin.get('creative_plan')):
            raise BatchError('A researched creative plan is required before image generation')
        if manifest['image_attempts'] >= manifest['image_attempt_budget']:
            raise BatchError('Batch image attempt budget exhausted')
        if pin.get('attempts', 0) >= 4:
            raise BatchError('Pin repair limit reached')
        pin['attempts'] = pin.get('attempts', 0) + 1
        pin['repair_attempts'] = max(0, pin['attempts'] - 1)
        manifest['image_attempts'] += 1
        save_manifest(batch_dir, manifest)
        return pin['attempts']


def record_image_failure(batch_dir, pin_id, reason):
    """Persist a failed generation; close a pin after three failed repairs."""
    if not isinstance(reason, str) or not reason.strip() or '\n' in reason or '\r' in reason:
        raise BatchError('A concise one-line failure reason is required')
    reason = ' '.join(reason.split())
    if len(reason) > 160 or re.search(r'(?i)(api[_-]?key|token|secret|password|authorization)\s*[:=]|\bbearer\s+\S+', reason):
        raise BatchError('Failure reason is too long or may contain a secret')
    with batch_lock(batch_dir):
        manifest = load_manifest(batch_dir)
        pin = next((item for item in manifest['pins'] if item['pin_id'] == pin_id), None)
        if pin is None:
            raise BatchError('Unknown pin ID')
        if manifest.get('state') != 'active' or pin.get('outcome') in ('uploaded', 'omitted', 'rejected'):
            raise BatchError('Pin is closed to image failures')
        attempt = pin.get('attempts', 0)
        if attempt < 1 or pin.get('last_failure_attempt') == attempt:
            raise BatchError('No unrecorded image attempt is available to fail')
        pin['last_failure_attempt'] = attempt
        pin['failed_attempts'] = pin.get('failed_attempts', 0) + 1
        if attempt > 1:
            pin['failed_repairs'] = pin.get('failed_repairs', 0) + 1
        pin['last_failure_reason'] = reason
        if pin.get('failed_repairs', 0) >= 3:
            pin['outcome'] = 'omitted'
            pin['omission_reason'] = reason
        save_manifest(batch_dir, manifest)
        return pin


def validate_pin_plan(manifest):
    recovery = 'Malformed pin plan; restore a valid manifest or reconcile this batch before continuing'
    if not isinstance(manifest, dict):
        raise BatchError(recovery)
    if not isinstance(manifest.get('batch_id'), str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,79}', manifest['batch_id']) or manifest.get('state') not in ('active', 'exported', 'blocked', 'uploaded'):
        raise BatchError(recovery)
    if not isinstance(manifest.get('exports'), list) or any(not isinstance(e, dict) for e in manifest['exports']) or not isinstance(manifest.get('reservations', []), list):
        raise BatchError(recovery)
    if not isinstance(manifest.get('approved_urls'), list) or not all(https_url(url) for url in manifest['approved_urls']) or not isinstance(manifest.get('pins'), list):
        raise BatchError(recovery)
    urls = manifest['approved_urls']
    pins = manifest['pins']
    for pin in pins:
        if not isinstance(pin, dict) or any(not isinstance(pin.get(field), str) or not pin[field].strip() for field in ('pin_id', 'affiliate_url', 'board', 'kind')) or type(pin.get('slot')) is not int:
            raise BatchError(recovery)
        for field in (FIELDS | OPTIONAL_FIELDS) & pin.keys():
            value = pin[field]
            if field == 'reviewed':
                valid = type(value) is bool
            elif field == 'keywords':
                valid = isinstance(value, list) and bool(value) and all(isinstance(v, str) and v.strip() for v in value)
            elif field in ('creative_plan', 'review_evidence'):
                valid = isinstance(value, dict) and bool(value)
                if valid and field == 'creative_plan':
                    valid = creative_plan_complete(value)
                if valid and field == 'review_evidence':
                    required_review = {'verdict', 'content_hash', 'source_hash', 'board_hash', 'destination_hash', 'asset_sha256', 'reviewer', 'reviewed_at'}
                    valid = required_review.issubset(value) and value.get('verdict') == 'PASS'
            else:
                valid = isinstance(value, str) and bool(value.strip())
                if valid and field == 'source_sha256':
                    valid = bool(re.fullmatch(r'[a-fA-F0-9]{64}', value))
            if not valid:
                raise BatchError(recovery)
        if manifest.get('schema_version', 1) >= SCHEMA_VERSION and not manifest.get('legacy_plan'):
            plan = pin.get('creative_plan')
            if plan is not None and (not creative_plan_complete(plan) or plan.get('kind', pin.get('kind')) != pin.get('kind') or plan.get('slot', pin.get('slot')) != pin.get('slot')):
                raise BatchError(recovery)
    if (not urls and manifest.get('batch_size', 0) != 0) or len(set(urls)) != len(urls) or any(p['affiliate_url'] not in urls for p in pins):
        raise BatchError('Pin plan differs from approved URLs')
    if len({p['pin_id'] for p in pins}) != len(pins):
        raise BatchError('Duplicate pin IDs')
    if manifest.get('legacy_plan') or manifest.get('schema_version', 1) < SCHEMA_VERSION:
        for url in urls:
            group = [p for p in pins if p['affiliate_url'] == url]
            if group and (len(group) != 10 or {p['slot'] for p in group} != set(range(1, 11)) or any(p['kind'] != ('guide' if p['slot'] <= 5 else 'promotion') for p in group)):
                raise BatchError('Malformed legacy pin plan')
            for field in ('title', 'description', 'image_path', 'media_url', 'remote_file_id'):
                values = [p[field] for p in group if field in p]
                if field in ('title', 'description'):
                    values = [' '.join(value.split()).casefold() for value in values]
                if len(set(values)) != len(values):
                    raise BatchError(f'Each approved URL requires distinct {field} values')
    else:
        if type(manifest.get('batch_size')) is not int or len(pins) != manifest['batch_size']:
            raise BatchError(recovery)
        if len({(pin.get('product'), pin.get('slot')) for pin in pins}) != len(pins):
            raise BatchError('Duplicate product slot')
        primary = manifest.get('primary_destinations')
        if not isinstance(primary, dict):
            raise BatchError(recovery)
        for pin in pins:
            boards = pin.get('eligible_boards')
            if not isinstance(boards, list) or not boards or pin['board'] not in boards:
                raise BatchError('Pin board is outside its eligible board mapping')
            if pin.get('destination_url') != primary.get(pin.get('product')):
                raise BatchError('Pin destination differs from its configured primary destination')
            if pin['kind'] not in ('guide', 'promotion'):
                raise BatchError(recovery)
        if pins and any(left['kind'] == right['kind'] for left, right in zip(pins, pins[1:])):
            raise BatchError('Current pin plan must alternate guide and promotion kinds')
        for product in {pin.get('product') for pin in pins}:
            group = [pin for pin in pins if pin.get('product') == product]
            for field in ('title', 'description', 'image_path', 'media_url', 'remote_file_id'):
                values = [pin[field] for pin in group if field in pin]
                if field in ('title', 'description'):
                    values = [' '.join(value.split()).casefold() for value in values]
                if len(set(values)) != len(values):
                    raise BatchError(f'Each product requires distinct {field} values')
    short_urls = [p['short_url'] for p in pins if p.get('short_url')]
    if len(set(short_urls)) != len(short_urls):
        raise BatchError('Duplicate short_url values; each pin requires its own link')


def pending_pins(batch_dir):
    manifest = load_manifest(batch_dir)
    if manifest.get('schema_version', 1) < SCHEMA_VERSION:
        manifest = dict(manifest, pins=[dict(pin, _legacy=True) for pin in manifest.get('pins', [])])
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
        if manifest.get('schema_version', 1) < SCHEMA_VERSION:
            raise BatchError('Legacy batch is read-only; migrate an unfinished batch before exporting')
        if manifest['state'] in ('uploaded', 'blocked'):
            raise BatchError('Batch is uploaded or blocked; explicit reconciliation is required')
        try:
            check_approval(manifest, approved_path)
        except BatchError:
            manifest.update(state='blocked', blocked_reason='Approved destination was revoked')
            for export in manifest['exports']:
                export['invalidated'] = True
            save_manifest(batch_dir, manifest)
            raise
        if manifest.get('reservations') and manifest['reservations'][-1].get('status') in ('reserved', 'exported'):
            raise BatchError('The previous export must receive an import outcome before another export')
        active_pins = [pin for pin in manifest['pins'] if pin.get('outcome') not in ('uploaded', 'omitted', 'rejected')]
        eligible = [pin for pin in active_pins if complete_pin(batch_dir, pin, require_verification=False)]
        if not eligible:
            manifest.update(state='blocked', export_status='BLOCKED', blocked_reason='No passing pins are eligible for export')
            save_manifest(batch_dir, manifest)
            raise BatchError('No passing pins are eligible for export; batch is BLOCKED')
        reservation = {'reservation_id': hashlib.sha256(f"{manifest['batch_id']}|{len(manifest.get('reservations', [])) + 1}|{timestamp()}".encode()).hexdigest()[:16], 'status': 'reserved', 'pin_ids': [pin['pin_id'] for pin in eligible], 'created_at': timestamp()}
        manifest.setdefault('reservations', []).append(reservation)
        save_manifest(batch_dir, manifest)
        if verify_pins is not None:
            try:
                verify_pins(dict(manifest, pins=eligible), Path(batch_dir))
                check_approval(manifest, approved_path)
                validate_pin_plan(manifest)
                eligible = weave_export_pins([pin for pin in eligible if complete_pin(batch_dir, pin)])
                if not eligible:
                    raise BatchError('Live verification left no passing pins; batch is BLOCKED')
            except (ValueError, OSError):
                manifest.update(state='blocked', blocked_reason='Live export verification failed; see reported error')
                reservation['status'] = 'failed'
                for export in manifest['exports']:
                    export['invalidated'] = True
                save_manifest(batch_dir, manifest)
                raise
        # The anchor is the successful final verification time. Scheduling is
        # planned in Johannesburg local time, then written to the CSV in UTC.
        now = now or utc_now()
        if now.tzinfo is None:
            raise BatchError('Export time requires a timezone')
        now = now.astimezone(timezone.utc)
        # Serialize allocation across sibling batches. Persist the reservation
        # before writing the CSV so another export cannot select the same slots.
        try:
            with batch_lock(Path(batch_dir).parent / '.schedule-lock'):
                schedule_slots = plan_schedule_slots(now, len(eligible), Path(batch_dir).parent)
                reservation['schedule_slots'] = schedule_slots
                save_manifest(batch_dir, manifest)
        except (BatchError, OSError):
            manifest['reservations'].remove(reservation)
            save_manifest(batch_dir, manifest)
            raise
        version = len(manifest['exports']) + 1
        path = Path(batch_dir) / f'pinterest-{manifest["batch_id"]}-v{version:03d}.csv'
        while path.exists():
            version += 1
            path = Path(batch_dir) / f'pinterest-{manifest["batch_id"]}-v{version:03d}.csv'
        temporary = path.with_suffix('.csv.tmp')
        try:
            with temporary.open('w', encoding='utf-8', newline='') as stream:
                writer = csv.writer(stream)
                writer.writerow(HEADERS)
                for n, p in enumerate(eligible):
                    date = schedule_slots[n]
                    writer.writerow([p['title'], p['media_url'], p['board'], p['description'], p['short_url'], date, ', '.join(p['keywords'])])
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        except OSError:
            if temporary.exists():
                temporary.unlink()
            reservation.update(status='cancelled', lifecycle='CANCELLED', cancelled_at=timestamp())
            save_manifest(batch_dir, manifest)
            raise
        status = 'READY_FULL' if len(eligible) == len(active_pins) else 'READY_PARTIAL'
        result = {'path': str(path.resolve()), 'version': version, 'exported_at': now.isoformat(), 'rows': len(eligible), 'status': status, 'reservation_id': reservation['reservation_id'], 'age_seconds': 0, 'scheduling_timezone': 'Africa/Johannesburg', 'schedule_slots': schedule_slots}
        manifest['exports'].append(result)
        reservation.update(status='exported', export_version=version, pin_ids=[pin['pin_id'] for pin in eligible], schedule_slots=schedule_slots)
        if status == 'READY_PARTIAL':
            eligible_ids = {pin['pin_id'] for pin in eligible}
            for pin in active_pins:
                if pin['pin_id'] not in eligible_ids:
                    pin['outcome'] = 'omitted'
                    pin['omission_reason'] = 'Did not pass all per-Pin readiness gates at handoff'
        manifest['export_status'] = status
        manifest['state'] = 'exported'
        save_manifest(batch_dir, manifest)
        return result


def import_outcome(batch_dir, reservation_id, outcomes):
    """Close an export reservation with one explicit result per handed-off pin."""
    with batch_lock(batch_dir):
        manifest = load_manifest(batch_dir)
        if manifest.get('schema_version', 1) >= SCHEMA_VERSION:
            raise BatchError('Current exports use whole-export lifecycle; use confirm_uploaded or cancel_export')
        reservation = next((item for item in manifest.get('reservations', []) if item.get('reservation_id') == reservation_id), None)
        if reservation is None or reservation.get('status') != 'exported':
            raise BatchError('Unknown or unresolved export reservation')
        if reservation.get('schedule_slots') and (
                not isinstance(outcomes, dict) or
                set(outcomes.values()) != {'uploaded'}):
            raise BatchError('Current exports require whole-export upload confirmation or cancellation')
        if reservation.get('schedule_slots'):
            reservation.update(status='uploaded', lifecycle='UPLOADED', uploaded_at=timestamp())
            manifest['outcome'] = {'reservation_id': reservation_id, 'status': 'UPLOADED', 'recorded_at': timestamp()}
            manifest['state'] = 'uploaded'
            save_manifest(batch_dir, manifest)
            return manifest
        if not isinstance(outcomes, dict) or set(outcomes) != set(reservation['pin_ids']) or any(value not in ('uploaded', 'rejected', 'omitted') for value in outcomes.values()):
            raise BatchError('Import outcome must cover every reserved pin as uploaded, rejected or omitted')
        reservation.update(status='closed', outcomes=dict(outcomes), closed_at=timestamp())
        for pin in manifest['pins']:
            if pin['pin_id'] in outcomes:
                pin['outcome'] = outcomes[pin['pin_id']]
        manifest['outcome'] = {'reservation_id': reservation_id, 'outcomes': dict(outcomes), 'recorded_at': timestamp()}
        manifest['state'] = 'uploaded' if manifest['pins'] and all(pin.get('outcome') in ('uploaded', 'omitted') for pin in manifest['pins']) else 'active'
        if manifest['state'] == 'uploaded':
            manifest['uploaded_at'] = timestamp()
        save_manifest(batch_dir, manifest)
        return manifest


def mark_uploaded(batch_dir):
    return confirm_uploaded(batch_dir)


def confirm_uploaded(batch_dir, reservation_id=None):
    """Confirm a whole export import and permanently consume its slots."""
    with batch_lock(batch_dir):
        manifest = load_manifest(batch_dir)
        reservations = manifest.get('reservations', [])
        reservation = (next((item for item in reservations if item.get('reservation_id') == reservation_id), None)
                       if reservation_id else (reservations[-1] if reservations else None))
        if reservation is None or reservation.get('status') not in ('exported', 'RESERVED', 'reserved'):
            raise BatchError('Unknown or unresolved export reservation')
        reservation.update(status='uploaded', lifecycle='UPLOADED', uploaded_at=timestamp())
        manifest['state'] = 'uploaded'
        manifest['outcome'] = {'reservation_id': reservation['reservation_id'], 'status': 'UPLOADED', 'recorded_at': timestamp()}
        save_manifest(batch_dir, manifest)
        return manifest


def cancel_export(batch_dir, reservation_id=None):
    """Cancel one whole export, releasing its reserved schedule slots."""
    with batch_lock(batch_dir):
        manifest = load_manifest(batch_dir)
        reservations = manifest.get('reservations', [])
        reservation = (next((item for item in reservations if item.get('reservation_id') == reservation_id), None)
                       if reservation_id else (reservations[-1] if reservations else None))
        if reservation is None or reservation.get('status') not in ('exported', 'RESERVED', 'reserved'):
            raise BatchError('Unknown or unresolved export reservation')
        reservation.update(status='cancelled', lifecycle='CANCELLED', cancelled_at=timestamp())
        export = next((item for item in manifest.get('exports', []) if item.get('reservation_id') == reservation['reservation_id']), None)
        if export:
            export['cancelled'] = True
        manifest['state'] = 'active'
        manifest['outcome'] = {'reservation_id': reservation['reservation_id'], 'status': 'CANCELLED', 'recorded_at': timestamp()}
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
    for name in ('init', 'status', 'pending', 'record', 'image-failure', 'export', 'mark-uploaded', 'confirm-uploaded', 'cancel-export', 'block', 'resume', 'migrate'):
        command = commands.add_parser(name)
        command.add_argument('--batch', required=True)
        if name == 'init':
            command.add_argument('--pilot', action='store_true')
            command.add_argument('--batch-size', type=int, default=DEFAULT_BATCH_SIZE)
            command.add_argument('--allocation-cursor', type=int, default=None)
        if name == 'record':
            command.add_argument('--pin', required=True)
            command.add_argument('--data', required=True)
        if name == 'image-failure':
            command.add_argument('--pin', required=True)
            command.add_argument('--reason', required=True)
        if name in ('confirm-uploaded', 'cancel-export'):
            command.add_argument('--reservation-id', required=False)
        if name == 'block':
            command.add_argument('--reason', required=True)
    args = parser.parse_args(argv)
    try:
        directory = Path(args.batches_root) / args.batch
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,79}', args.batch):
            raise BatchError('Invalid batch ID')
        if args.command == 'init':
            manifest = init_batch(args.batch, args.batches_root, args.approved_file, args.pilot, args.batch_size, allocation_cursor=args.allocation_cursor)
            result = {'batch_id': manifest['batch_id'], 'state': manifest['state'], 'pins': len(manifest['pins'])}
        elif args.command == 'migrate':
            manifest = migrate_legacy_batch(directory, args.approved_file)
            result = {'batch_id': manifest['batch_id'], 'schema_version': manifest['schema_version'], 'state': manifest['state']}
        elif args.command == 'pending':
            result = pending_pins(directory)
        elif args.command == 'export':
            raise BatchError('Use pinterest_export.py for live-verified CSV export')
        elif args.command == 'record':
            record_pin(directory, args.pin, json.loads(Path(args.data).read_text(encoding='utf-8-sig')), args.approved_file)
            result = {'recorded': args.pin}
        elif args.command == 'image-failure':
            pin = record_image_failure(directory, args.pin, args.reason)
            result = {'pin': args.pin, 'failed_attempts': pin['failed_attempts'], 'failed_repairs': pin['failed_repairs'], 'outcome': pin.get('outcome')}
        elif args.command == 'mark-uploaded':
            result = {'state': mark_uploaded(directory)['state']}
        elif args.command == 'confirm-uploaded':
            result = {'state': confirm_uploaded(directory, args.reservation_id)['state']}
        elif args.command == 'cancel-export':
            result = {'state': cancel_export(directory, args.reservation_id)['state']}
        elif args.command == 'block':
            result = {'state': block_batch(directory, args.reason)['state']}
        elif args.command == 'resume':
            result = {'state': resume_batch(directory, args.approved_file)['state']}
        else:
            manifest = load_manifest(directory)
            try:
                validate_pin_plan(manifest)
                legacy_pins = [dict(pin, _legacy=True) for pin in manifest['pins']] if manifest.get('schema_version', 1) < SCHEMA_VERSION else manifest['pins']
                complete = sum(complete_pin(directory, pin) for pin in legacy_pins)
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
