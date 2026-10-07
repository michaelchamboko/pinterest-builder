"""ImageKit uploads with exact-path reconciliation and durable recovery receipts."""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import sys
from urllib.error import HTTPError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
import uuid

import pinterest_batch as batch
from pinterest_services import ServiceError, load_env, verify_media

LIST_URL = 'https://api.imagekit.io/v1/files'
UPLOAD_URL = 'https://upload.imagekit.io/api/v1/files/upload'


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def api(url, key, body=None, content_type=None):
    parsed = urlsplit(url)
    if url.split('?')[0] not in (LIST_URL, UPLOAD_URL) or parsed.fragment:
        raise ServiceError('ImageKit credential destination rejected')
    if not key:
        raise ServiceError('IMAGEKIT_PRIVATE_KEY missing')
    try:
        headers = {'Authorization': 'Basic ' + base64.b64encode((key + ':').encode()).decode()}
        if content_type:
            headers['Content-Type'] = content_type
        request = Request(url, data=body, headers=headers, method='POST' if body is not None else 'GET')
        with build_opener(NoRedirect()).open(request, timeout=90) as response:
            return json.load(response)
    except HTTPError as exc:
        raise ServiceError('ImageKit HTTP status ' + str(exc.code)) from None
    except Exception as exc:
        raise ServiceError('ImageKit request failed: ' + type(exc).__name__) from None


def multipart(data, folder, filename):
    boundary = uuid.uuid4().hex
    fields = {'fileName': filename, 'folder': folder, 'useUniqueFileName': 'false', 'overwriteFile': 'false', 'isPrivateFile': 'false'}
    chunks = []
    for name, value in fields.items():
        chunks.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
    chunks.extend([f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\nContent-Type: application/octet-stream\r\n\r\n'.encode(), data, f'\r\n--{boundary}--\r\n'.encode()])
    return b''.join(chunks), 'multipart/form-data; boundary=' + boundary


def preflight_read(key):
    """Authenticate with a bounded, read-only listing; retain no asset details."""
    results = api(LIST_URL + '?type=file&limit=1', key)
    if not isinstance(results, list):
        raise ServiceError('ImageKit list response malformed')
    return {'authenticated': True, 'operation': 'list-files', 'returned_count': len(results)}


def validate_asset(asset, expected):
    if not isinstance(asset, dict) or asset.get('filePath') != expected:
        raise ServiceError('ImageKit response file path mismatch')
    if not isinstance(asset.get('fileId'), str) or not asset['fileId'] or not batch.https_url(asset.get('url')):
        raise ServiceError('ImageKit response missing media URL or file ID')
    parsed = urlsplit(asset['url'])
    if parsed.query or parsed.fragment or asset.get('isPrivateFile') is True:
        raise ServiceError('ImageKit media must use a plain public URL')
    if not parsed.path.endswith(expected):
        raise ServiceError('ImageKit delivery URL differs from expected file path')
    endpoint_path = parsed.path[:-len(expected)]
    if parsed.hostname == 'ik.imagekit.io' and not re.fullmatch(r'/[^/]+', endpoint_path):
        raise ServiceError('ImageKit delivery endpoint is malformed')
    # Original delivery bypasses optimization so public bytes match the local asset.
    original_path = endpoint_path + '/tr:orig-true' + expected
    original_url = parsed._replace(path=original_path).geturl()
    return {'media_url': original_url, 'remote_file_id': asset['fileId']}


def save_receipt(receipt, asset):
    """Publish complete JSON atomically, without replacing another caller's receipt."""
    receipt.parent.mkdir(parents=True, exist_ok=True)
    temporary = receipt.with_name(receipt.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with temporary.open('x', encoding='utf-8') as stream:
            json.dump(asset, stream, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        # A same-volume hard link atomically publishes and fails if the name exists.
        os.link(temporary, receipt)
    finally:
        temporary.unlink(missing_ok=True)


def upload_image(path, folder, filename, key, *, receipt=None):
    if not re.fullmatch(r'/[A-Za-z0-9_/-]+/', folder) or not re.fullmatch(r'[A-Za-z0-9_-]+\.(png|jpg|jpeg)', filename):
        raise ServiceError('Unsafe ImageKit folder or filename')
    expected = folder + filename
    path = Path(path)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    receipt = Path(receipt) if receipt else None
    if receipt and receipt.exists():
        asset = json.loads(receipt.read_text(encoding='utf-8'))
        if asset.get('local_sha256') != digest:
            raise ServiceError('Receipt belongs to different local image bytes')
    else:
        asset = None
        skip = 0
        while True:
            results = api(LIST_URL + '?' + urlencode({'path': folder, 'type': 'file', 'limit': 1000, 'skip': skip}), key)
            if not isinstance(results, list):
                raise ServiceError('ImageKit list response malformed')
            exact = [item for item in results if isinstance(item, dict) and item.get('filePath') == expected]
            if exact:
                if len(exact) != 1:
                    raise ServiceError('Multiple assets share expected path')
                asset = exact[0]
                break
            if len(results) < 1000:
                break
            skip += 1000
        if asset is None:
            data, content_type = multipart(path.read_bytes(), folder, filename)
            asset = api(UPLOAD_URL, key, data, content_type)
        if not isinstance(asset, dict):
            raise ServiceError('ImageKit upload response malformed; reconcile before retry')
        asset = {k: asset.get(k) for k in ('fileId', 'filePath', 'url', 'isPrivateFile')}
        asset['local_sha256'] = digest
        if receipt:
            save_receipt(receipt, asset)
    result = validate_asset(asset, expected)
    evidence = verify_media(result['media_url'], path)
    result['media_verified_at'] = evidence['media_verified_at']
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--batch', required=True)
    parser.add_argument('--pin', required=True)
    parser.add_argument('--output', required=True, help='Durable API receipt path, reused on resume')
    parser.add_argument('--batches-root', default='batches')
    parser.add_argument('--approved-file', default=str(batch.DEFAULT_APPROVED))
    parser.add_argument('--env-file', default=str(Path(__file__).with_name('.env.local')))
    args = parser.parse_args(argv)
    try:
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,79}', args.batch):
            raise ServiceError('Invalid batch ID')
        directory = (Path(args.batches_root) / args.batch).resolve()
        manifest = batch.load_manifest(directory)
        batch.check_approval(manifest, args.approved_file)
        if manifest['state'] in ('uploaded', 'blocked'):
            raise ServiceError('Batch is uploaded or blocked')
        pin = next((p for p in manifest['pins'] if p['pin_id'] == args.pin), None)
        if pin is None:
            raise ServiceError('Unknown pin ID')
        path = (directory / pin.get('image_path', '')).resolve()
        if not path.is_relative_to(directory) or not path.is_file():
            raise ServiceError('Image must exist inside the selected batch')
        if not pin['imagekit_folder'].startswith('/pinterest/' + args.batch + '/'):
            raise ServiceError('ImageKit folder differs from selected batch')
        if pin.get('remote_file_id') and pin.get('media_url'):
            evidence = verify_media(pin['media_url'], path)
            result = {'media_url': pin['media_url'], 'remote_file_id': pin['remote_file_id'], 'media_verified_at': evidence['media_verified_at']}
        else:
            env = load_env(args.env_file)
            key = os.environ.get('IMAGEKIT_PRIVATE_KEY') or env.get('IMAGEKIT_PRIVATE_KEY')
            result = upload_image(path, pin['imagekit_folder'], pin['image_filename'], key, receipt=args.output)
        batch.record_pin(directory, args.pin, result, args.approved_file)
        with batch.batch_lock(directory):
            manifest = batch.load_manifest(directory)
            batch.check_approval(manifest, args.approved_file)
            recorded = next(p for p in manifest['pins'] if p['pin_id'] == args.pin)
            if manifest['state'] != 'active' or recorded.get('media_url') != result['media_url'] or (directory / recorded.get('image_path', '')).resolve() != path:
                raise ServiceError('Media changed during upload verification; retry verification')
            recorded['media_verified_at'] = result['media_verified_at']
            batch.save_manifest(directory, manifest)
        print(json.dumps({'pin_id': args.pin, **result}))
        return 0
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(str(exc) if isinstance(exc, ServiceError) else 'ImageKit operation failed: ' + type(exc).__name__, file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
