"""Explicit service operations; credentials never enter public media/link requests."""
import argparse
import hashlib
import http.client
import io
import ipaddress
import json
import os
from pathlib import Path
import re
import socket
import ssl
import sys
import tomllib
from datetime import datetime, timezone
from urllib.parse import urljoin, urlsplit

# justonemedia.short.gy is the current production default. Keep the previous
# domain allowlisted so existing receipts and legacy links remain verifiable.
DOMAIN = 'justonemedia.short.gy'
LEGACY_DOMAIN = 'vettedsaasblueprint.s.gy'
ALLOWED_DOMAINS = (DOMAIN, LEGACY_DOMAIN)
MAX_BYTES = 20 * 1024 * 1024
USER_AGENT = 'Mozilla/5.0 (compatible; PinterestAssetVerification/1.0)'


class ServiceError(ValueError):
    pass


def timestamp():
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def load_env(path='.env.local'):
    values = {}
    if Path(path).exists():
        for line in Path(path).read_text(encoding='utf-8-sig').splitlines():
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            if line.startswith('export '):
                line = line[7:]
            key, separator, value = line.partition('=')
            if separator:
                values[key.strip()] = value.strip().strip('\"\'')
    return values


def imagekit_configured(config_path=None):
    """Inspect only ImageKit's MCP endpoint; never return configuration contents."""
    path = Path(config_path) if config_path else Path.home() / '.codex' / 'config.toml'
    if not path.exists():
        return False
    with path.open('rb') as stream:
        config = tomllib.load(stream)
    server = config.get('mcp_servers', {}).get('imagekit_dam', {})
    return isinstance(server, dict) and server.get('enabled', True) is not False and bool(server.get('url') or server.get('command'))


def public_address(host, port):
    try:
        addresses = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
            raise ServiceError('Non-public destination rejected')
        return addresses[0][4][0]
    except ServiceError:
        raise
    except Exception as exc:
        raise ServiceError('DNS failed: ' + type(exc).__name__) from None


def request(url, *, method='GET', headers=None, body=None, max_bytes=MAX_BYTES):
    """One hop, with the validated DNS address pinned to the socket; no redirects."""
    connection = None
    try:
        if any(c.isspace() or c in '\\<>"' for c in url):
            raise ServiceError('Invalid public URL')
        parsed = urlsplit(url)
        if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password:
            raise ServiceError('Invalid public URL')
        port = parsed.port or (443 if parsed.scheme == 'https' else 80)
        if port != (443 if parsed.scheme == 'https' else 80):
            raise ServiceError('Nonstandard destination port rejected')
        headers = dict(headers or {})
        if any(k.lower() == 'authorization' for k in headers) and (parsed.scheme != 'https' or parsed.hostname != 'api.short.io'):
            raise ServiceError('Credential destination rejected')
        address = public_address(parsed.hostname, port)
        connection = http.client.HTTPConnection(parsed.hostname, port, timeout=30)
        connection.sock = socket.create_connection((address, port), timeout=30)
        if parsed.scheme == 'https':
            connection.sock = ssl.create_default_context().wrap_socket(connection.sock, server_hostname=parsed.hostname)
        headers['User-Agent'] = USER_AGENT
        payload = None if body is None else json.dumps(body).encode()
        if payload is not None:
            headers['Content-Type'] = 'application/json'
        target = parsed.path or '/'
        if parsed.query:
            target += '?' + parsed.query
        connection.request(method, target, body=payload, headers=headers)
        response = connection.getresponse()
        result_headers = {k.lower(): v for k, v in response.getheaders()}
        data = response.read(max_bytes + 1)
        if len(data) > max_bytes:
            raise ServiceError('Response exceeds size limit')
        return response.status, result_headers, data
    except ServiceError:
        raise
    except Exception as exc:
        raise ServiceError('HTTP failed: ' + type(exc).__name__) from None
    finally:
        if connection:
            connection.close()


def api_json(path, api_key, *, body=None, transport=None):
    if not api_key:
        raise ServiceError('SHORTIO_API_KEY is missing')
    try:
        status, _, data = (transport or request)('https://api.short.io/' + path, method='POST' if body is not None else 'GET', headers={'Authorization': api_key}, body=body)
        if status not in (200, 201):
            raise ServiceError('Short.io HTTP status ' + str(status))
        return json.loads(data)
    except ServiceError:
        raise
    except Exception as exc:
        raise ServiceError('Short.io failed: ' + type(exc).__name__) from None


def check_short_url(url, *, allow_legacy=True):
    parsed = urlsplit(url)
    domains = ALLOWED_DOMAINS if allow_legacy else (DOMAIN,)
    if parsed.scheme != 'https' or parsed.netloc not in domains or not parsed.path.strip('/') or parsed.query or parsed.fragment:
        raise ServiceError('Unexpected Short.io URL')


def ensure_short_link(original_url, api_key, transport=None, path=None, domain=DOMAIN):
    from pinterest_batch import https_url
    if domain != DOMAIN:
        raise ServiceError('Unapproved Short.io domain')
    if not isinstance(path, str) or not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', path):
        raise ServiceError('Invalid Short.io path')
    if not https_url(original_url):
        raise ServiceError('Invalid original URL')
    body = {'domain': domain, 'originalURL': original_url, 'allowDuplicates': False}
    body['path'] = path
    result = api_json('links', api_key, body=body, transport=transport)
    if not isinstance(result, dict) or result.get('originalURL') != original_url:
        raise ServiceError('Short.io original URL mismatch')
    short_url = result.get('secureShortURL', '')
    check_short_url(short_url, allow_legacy=False)
    if urlsplit(short_url).netloc != domain:
        raise ServiceError('Short.io returned an unexpected domain')
    if urlsplit(short_url).path != '/' + path:
        raise ServiceError('Short.io returned an unexpected path')
    link_id = result.get('idString') or result.get('id')
    if not isinstance(link_id, (str, int)) or isinstance(link_id, bool) or not str(link_id):
        raise ServiceError('Short.io link ID missing')
    return {'short_url': short_url, 'short_link_id': str(link_id), 'original_url': original_url}


def follow_public(url):
    chain = []
    for _ in range(11):
        status, headers, data = request(url)
        chain.append({'url': url, 'status': status})
        if status in (301, 302, 303, 307, 308):
            if not headers.get('location'):
                raise ServiceError('Redirect lacks Location')
            url = urljoin(url, headers['location'])
            continue
        if status != 200:
            raise ServiceError('Public URL HTTP status ' + str(status))
        return url, headers, data, chain
    raise ServiceError('Too many redirects')


def verify_link(short_url, original_url):
    check_short_url(short_url)
    status, headers, _ = request(short_url)
    if status not in (301, 302, 303, 307, 308) or headers.get('location') != original_url:
        raise ServiceError('Short link first hop differs from exact approved URL')
    final, _, _, chain = follow_public(original_url)
    return {'short_url': short_url, 'original_url': original_url, 'final_url': final, 'redirect_chain': [{'url': short_url, 'status': status}] + chain, 'link_verified_at': timestamp()}


def verify_media(url, local=None):
    final, headers, data, _ = follow_public(url)
    mime = headers.get('content-type', '').split(';')[0].strip().lower()
    if mime not in ('image/png', 'image/jpeg'):
        raise ServiceError('Media Content-Type must be PNG or JPEG')
    try:
        from PIL import Image
        with Image.open(io.BytesIO(data)) as image:
            width, height = image.size
            if image.format not in ('PNG', 'JPEG') or mime != {'PNG': 'image/png', 'JPEG': 'image/jpeg'}[image.format]:
                raise ServiceError('Media format and Content-Type disagree')
            if width < 600 or height < 900 or abs((width / height) / (2 / 3) - 1) > .01:
                raise ServiceError('Media requires at least 600x900 pixels and 2:3 ratio')
            if width * height > 50_000_000:
                raise ServiceError('Decoded media exceeds pixel limit')
            image.verify()
        with Image.open(io.BytesIO(data)) as image:
            image.load()
    except ServiceError:
        raise
    except Exception as exc:
        raise ServiceError('Media decode failed: ' + type(exc).__name__) from None
    digest = hashlib.sha256(data).hexdigest()
    evidence = {'media_url': url, 'final_url': final, 'width': width, 'height': height, 'sha256': digest, 'bytes': len(data), 'media_verified_at': timestamp()}
    if local:
        if hashlib.sha256(Path(local).read_bytes()).hexdigest() != digest:
            raise ServiceError('Public media does not match the local image')
        evidence['image_path'] = str(Path(local).resolve())
    return evidence


def main(argv=None):
    from pinterest_batch import DEFAULT_APPROVED, parse_approved_urls
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env-file', default=str(Path(__file__).with_name('.env.local')))
    sub = parser.add_subparsers(dest='command', required=True)
    preflight = sub.add_parser('preflight')
    preflight.add_argument('--output', required=True)
    for name in ('shorten', 'verify-link', 'verify-media', 'verify-source'):
        command = sub.add_parser(name)
        command.add_argument('--url', required=True)
        command.add_argument('--output', required=True)
        if name == 'shorten':
            command.add_argument('--path', required=True)
            command.add_argument('--domain', choices=(DOMAIN,), default=DOMAIN)
        if name != 'verify-media':
            command.add_argument('--approved-file', default=str(DEFAULT_APPROVED))
        if name == 'verify-link':
            command.add_argument('--original', required=True)
        if name == 'verify-media':
            command.add_argument('--local')
    args = parser.parse_args(argv)
    try:
        env = load_env(args.env_file)
        key = os.environ.get('SHORTIO_API_KEY') or env.get('SHORTIO_API_KEY')
        if args.command in ('shorten', 'verify-link', 'verify-source'):
            original = args.original if args.command == 'verify-link' else args.url
            if original not in parse_approved_urls(args.approved_file):
                raise ServiceError('URL is not in the current approved file')
        if args.command == 'shorten':
            result = ensure_short_link(args.url, key, path=args.path, domain=args.domain)
        elif args.command == 'verify-link':
            result = verify_link(args.url, args.original)
        elif args.command == 'verify-media':
            result = verify_media(args.url, args.local)
        elif args.command == 'verify-source':
            final, _, _, chain = follow_public(args.url)
            result = {'source_url': final, 'source_checked_at': timestamp(), 'redirect_chain': chain}
        else:
            domains = api_json('api/domains', key)
            access = isinstance(domains, list) and any(isinstance(d, dict) and d.get('hostname') == DOMAIN for d in domains)
            if not access:
                raise ServiceError('Short.io configured domain access not verified')
            from pinterest_imagekit import preflight_read
            imagekit_key = os.environ.get('IMAGEKIT_PRIVATE_KEY') or env.get('IMAGEKIT_PRIVATE_KEY')
            result = {'shortio_domain_access': True, 'imagekit_configured': imagekit_configured(), 'imagekit_authentication': preflight_read(imagekit_key), 'verified_at': timestamp()}
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
        print(str(output.resolve()))
        return 0
    except (ValueError, OSError) as exc:
        print(str(exc) if isinstance(exc, ServiceError) else 'Operation failed: ' + type(exc).__name__, file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
