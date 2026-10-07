import io
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

import pinterest_services as s


class ServicesTests(unittest.TestCase):
    def test_legacy_creation_and_wrong_response_path_are_rejected(self):
        transport = unittest.mock.Mock()
        with self.assertRaises(s.ServiceError):
            s.ensure_short_link('https://example.com', 'secret', transport, path='pin-1', domain=s.LEGACY_DOMAIN)
        transport.assert_not_called()
        transport.return_value = (200, {}, s.json.dumps({'originalURL': 'https://example.com', 'secureShortURL': 'https://' + s.DOMAIN + '/other', 'idString': '1'}).encode())
        with self.assertRaisesRegex(s.ServiceError, 'path'):
            s.ensure_short_link('https://example.com', 'secret', transport, path='pin-1')

    def test_shorten_cli_requires_path(self):
        with patch('sys.stderr'), patch.object(s, 'ensure_short_link') as create:
            with self.assertRaises(SystemExit):
                s.main(['shorten', '--url', 'https://example.com', '--output', 'unused.json'])
            create.assert_not_called()

    def test_preflight_records_authenticated_read_evidence(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / 'preflight.json'
            with patch.object(s, 'load_env', return_value={'SHORTIO_API_KEY': 'short-secret', 'IMAGEKIT_PRIVATE_KEY': 'image-secret'}), patch.dict(s.os.environ, {'SHORTIO_API_KEY': '', 'IMAGEKIT_PRIVATE_KEY': ''}), patch.object(s, 'api_json', return_value=[{'hostname': s.DOMAIN}]), patch('pinterest_imagekit.api', return_value=[]) as api, patch('sys.stdout'):
                self.assertEqual(0, s.main(['preflight', '--output', str(output)]))
            result = s.json.loads(output.read_text())
            self.assertTrue(result['imagekit_authentication']['authenticated'])
            self.assertEqual(0, result['imagekit_authentication']['returned_count'])
            self.assertNotIn('secret', output.read_text())
            self.assertEqual('image-secret', api.call_args.args[1])

    def test_current_shortio_domain_is_the_default_and_legacy_domain_remains_allowed(self):
        self.assertEqual(s.DOMAIN, 'justonemedia.short.gy')
        self.assertEqual(s.LEGACY_DOMAIN, 'vettedsaasblueprint.s.gy')
        self.assertEqual(s.ALLOWED_DOMAINS, (s.DOMAIN, s.LEGACY_DOMAIN))

    def test_short_creation_requires_path_before_network(self):
        transport = unittest.mock.Mock()
        with self.assertRaises(s.ServiceError):
            s.ensure_short_link('https://example.com', 'secret', transport)
        transport.assert_not_called()

    def test_short_creation_accepts_custom_path_and_returns_idempotent_response(self):
        calls = []
        original = 'https://example.com/?ref=a%2Fb&x=1'
        response = {'originalURL': original, 'secureShortURL': 'https://' + s.DOMAIN + '/pin-2', 'idString': '123'}
        def transport(url, **kwargs):
            calls.append((url, kwargs))
            return 201, {}, s.json.dumps(response).encode()
        result = s.ensure_short_link(original, 'secret', transport, path='pin-2')
        self.assertEqual(result, {'short_url': response['secureShortURL'], 'short_link_id': '123', 'original_url': original})
        self.assertEqual(calls[0][1]['body'], {'domain': s.DOMAIN, 'originalURL': original, 'allowDuplicates': False, 'path': 'pin-2'})

    def test_short_creation_accepts_allowlisted_alternate_domain(self):
        calls = []
        original = 'https://example.com/?ref=a%2Fb&x=1'
        domain = 'justonemedia.short.gy'
        def transport(url, **kwargs):
            calls.append((url, kwargs))
            return 201, {}, s.json.dumps({'originalURL': original, 'secureShortURL': f'https://{domain}/pin-2', 'idString': '123'}).encode()
        result = s.ensure_short_link(original, 'secret', transport, path='pin-2', domain=domain)
        self.assertEqual(result['short_url'], f'https://{domain}/pin-2')
        self.assertEqual(calls[0][1]['body']['domain'], domain)

    def test_short_creation_rejects_unapproved_domain_before_network(self):
        transport = unittest.mock.Mock()
        with self.assertRaises(s.ServiceError):
            s.ensure_short_link('https://example.com', 'secret', transport, domain='spam.example')
        transport.assert_not_called()

    def test_short_creation_rejects_unsafe_custom_path_before_network(self):
        transport = unittest.mock.Mock()
        for path in ('Pin-2', 'pin_2', 'pin/2', 'pin 2', '', None):
            with self.subTest(path=path), self.assertRaises(s.ServiceError):
                s.ensure_short_link('https://example.com', 'secret', transport, path=path)
        transport.assert_not_called()

    def test_short_api_redirect_rejected(self):
        with self.assertRaises(s.ServiceError):
            s.ensure_short_link('https://example.com', 'secret', lambda *a, **k: (302, {'location': 'https://evil.com'}, b''), path='a')

    def test_credentials_rejected_before_dns_for_other_hosts(self):
        with patch.object(s, 'public_address') as resolve:
            with self.assertRaises(s.ServiceError):
                s.request('https://evil.com/', headers={'Authorization': 'secret'})
            resolve.assert_not_called()

    def test_api_errors_never_include_secret_or_response(self):
        def broken(*args, **kwargs):
            raise RuntimeError('secret')
        with self.assertRaises(s.ServiceError) as error:
            s.ensure_short_link('https://example.com', 'secret', broken, path='a')
        self.assertNotIn('secret', str(error.exception))

    def test_response_must_preserve_original_and_domain(self):
        for original, short in [('https://wrong.com', 'https://' + s.DOMAIN + '/a'), ('https://example.com', 'https://evil.com/a')]:
            with self.assertRaises(s.ServiceError):
                s.ensure_short_link('https://example.com', 'secret', lambda *a, **k: (200, {}, s.json.dumps({'originalURL': original, 'secureShortURL': short, 'idString': '1'}).encode()), path='a')

    def test_short_creation_rejects_response_on_wrong_requested_domain(self):
        original = 'https://example.com'
        with self.assertRaises(s.ServiceError):
            s.ensure_short_link(original, 'secret', lambda *a, **k: (200, {}, s.json.dumps({'originalURL': original, 'secureShortURL': 'https://' + s.LEGACY_DOMAIN + '/a', 'idString': '1'}).encode()), domain=s.DOMAIN, path='a')

    def test_link_preserves_exact_first_hop(self):
        original = 'https://example.com/?ref=a%2Fb'
        replies = iter([(302, {'location': original}, b''), (200, {}, b'')])
        with patch.object(s, 'request', side_effect=lambda *a, **k: next(replies)):
            self.assertIn('link_verified_at', s.verify_link('https://' + s.DOMAIN + '/a', original))
        with patch.object(s, 'request', return_value=(302, {'location': original.replace('%2F', '/')}, b'')):
            with self.assertRaises(s.ServiceError):
                s.verify_link('https://' + s.DOMAIN + '/a', original)

        replies = iter([(302, {'location': original}, b''), (200, {}, b'')])
        with patch.object(s, 'request', side_effect=lambda *a, **k: next(replies)):
            self.assertIn('link_verified_at', s.verify_link('https://justonemedia.short.gy/a', original))

    def test_private_dns_and_mixed_dns_rejected(self):
        for addresses in [('127.0.0.1',), ('8.8.8.8', '10.0.0.1')]:
            with patch.object(s.socket, 'getaddrinfo', return_value=[(2, 1, 6, '', (ip, 443)) for ip in addresses]):
                with self.assertRaises(s.ServiceError):
                    s.public_address('example.com', 443)

    def test_media_decodes_pixels(self):
        from PIL import Image
        stream = io.BytesIO()
        Image.new('RGB', (600, 900)).save(stream, format='PNG')
        with patch.object(s, 'request', return_value=(200, {'content-type': 'image/png'}, stream.getvalue())):
            self.assertEqual(s.verify_media('https://example.com/a')['width'], 600)
        with patch.object(s, 'request', return_value=(200, {'content-type': 'image/png'}, b'not an image')):
            with self.assertRaises(s.ServiceError):
                s.verify_media('https://example.com/a')

    def test_local_image_must_match_public_bytes(self):
        from PIL import Image
        stream = io.BytesIO()
        Image.new('RGB', (600, 900)).save(stream, format='PNG')
        with tempfile.TemporaryDirectory() as folder:
            local = Path(folder) / 'image.png'
            local.write_bytes(b'different')
            with patch.object(s, 'request', return_value=(200, {'content-type': 'image/png'}, stream.getvalue())):
                with self.assertRaises(s.ServiceError):
                    s.verify_media('https://example.com/a', local)
                local.write_bytes(stream.getvalue())
                self.assertEqual(s.verify_media('https://example.com/a', local)['image_path'], str(local.resolve()))

    def test_cli_checks_current_approval_before_remote_create(self):
        with patch('pinterest_batch.parse_approved_urls', return_value=['https://allowed.com']), patch.object(s, 'ensure_short_link') as create, patch('sys.stderr', new_callable=io.StringIO):
            self.assertEqual(s.main(['shorten', '--url', 'https://unapproved.com', '--output', 'unused.json', '--path', 'pin-1']), 1)
            create.assert_not_called()

    def test_source_approval_before_network_and_local_evidence(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / 'source.json'
            with patch('pinterest_batch.parse_approved_urls', return_value=['https://allowed.com']), patch.object(s, 'follow_public', return_value=('https://vendor.com', {}, b'ignored', [{'url': 'https://allowed.com', 'status': 200}])) as fetch, patch('sys.stderr', new_callable=io.StringIO), patch('sys.stdout', new_callable=io.StringIO):
                self.assertEqual(s.main(['verify-source', '--url', 'https://unapproved.com', '--output', str(output)]), 1)
                fetch.assert_not_called()
                self.assertEqual(s.main(['verify-source', '--url', 'https://allowed.com', '--output', str(output)]), 0)
                result = s.json.loads(output.read_text())
                self.assertEqual(result['source_url'], 'https://vendor.com')
                self.assertIn('source_checked_at', result)

    def test_imagekit_mcp_configuration_presence_only(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'config.toml'
            self.assertFalse(s.imagekit_configured(path))
            path.write_text('[mcp_servers.imagekit_dam]\nurl="https://example.com/mcp"\n')
            self.assertTrue(s.imagekit_configured(path))
            path.write_text('[mcp_servers.imagekit_dam]\nurl="https://example.com/mcp"\nenabled=false\n')
            self.assertFalse(s.imagekit_configured(path))

    def test_public_redirect_revalidates_private_host(self):
        replies = iter([(302, {'location': 'http://127.0.0.1/admin'}, b'')])
        real_request = s.request
        def fake(url, **kwargs):
            if url == 'https://example.com':
                return next(replies)
            return real_request(url, **kwargs)
        with patch.object(s, 'request', side_effect=fake), patch.object(s.socket, 'getaddrinfo', return_value=[(2, 1, 6, '', ('127.0.0.1', 80))]):
            with self.assertRaises(s.ServiceError):
                s.follow_public('https://example.com')


if __name__ == '__main__':
    unittest.main()
