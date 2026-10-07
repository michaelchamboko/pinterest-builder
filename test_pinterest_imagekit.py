import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import pinterest_imagekit as ik


class ImageKitTests(unittest.TestCase):
    def test_preflight_read_rejects_malformed_and_auth_failure(self):
        with patch.object(ik, 'api', return_value={'error': 'bad'}):
            with self.assertRaises(ik.ServiceError):
                ik.preflight_read('secret')
        with patch.object(ik, 'api', side_effect=ik.ServiceError('ImageKit HTTP status 401')):
            with self.assertRaises(ik.ServiceError):
                ik.preflight_read('secret')

    def test_cli_retains_trusted_evidence_after_recording_new_media(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            approved = root / 'approved.md'
            approved.write_text('- https://try.elevenlabs.io/example\n')
            campaign = {'ElevenLabs': {'primary_url': 'https://try.elevenlabs.io/example', 'eligible_boards': ['AI Tools & Automation']}}
            manifest = ik.batch.init_batch('pilot', root, approved, pilot=True, campaign=campaign)
            directory = root / 'pilot'
            (directory / 'image.png').write_bytes(b'image')
            pin_id = manifest['pins'][0]['pin_id']
            ik.batch.record_pin(directory, pin_id, {'image_path': 'image.png'}, approved)
            result = {'media_url': 'https://ik.imagekit.io/account/image.png', 'remote_file_id': '123', 'media_verified_at': '2026-10-07T10:00:00Z'}
            with patch.object(ik, 'upload_image', return_value=result), patch.object(ik, 'load_env', return_value={}), patch('sys.stdout'):
                self.assertEqual(0, ik.main(['--batch', 'pilot', '--pin', pin_id, '--output', str(root / 'receipt.json'), '--batches-root', str(root), '--approved-file', str(approved)]))
            self.assertEqual(result['media_verified_at'], ik.batch.load_manifest(directory)['pins'][0]['media_verified_at'])

    def test_auth_origin_locked(self):
        with self.assertRaises(ik.ServiceError):
            ik.api('https://evil.com', 'secret')

    def test_original_delivery_preserves_endpoint_and_raw_receipt(self):
        for endpoint in ('https://ik.imagekit.io/account', 'https://assets.example.com', 'https://assets.example.com/custom'):
            asset = {'filePath': '/pinterest/a.png', 'fileId': '1', 'url': endpoint + '/pinterest/a.png'}
            result = ik.validate_asset(asset, '/pinterest/a.png')
            self.assertEqual(result['media_url'], endpoint + '/tr:orig-true/pinterest/a.png')
            self.assertEqual(asset['url'], endpoint + '/pinterest/a.png')

    def test_exact_path_reused_without_upload(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'a.png'
            path.write_bytes(b'image')
            asset = {'filePath': '/pinterest/a.png', 'fileId': '123', 'url': 'https://ik.imagekit.io/account/pinterest/a.png'}
            with patch.object(ik, 'api', return_value=[asset]) as api, patch.object(ik, 'verify_media', return_value={'media_verified_at': 'now'}):
                self.assertEqual(ik.upload_image(path, '/pinterest/', 'a.png', 'secret')['remote_file_id'], '123')
                self.assertEqual(api.call_count, 1)

    def test_upload_receipt_precedes_failed_verification(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'a.png'
            path.write_bytes(b'image')
            receipt = Path(folder) / 'receipt.json'
            asset = {'filePath': '/pinterest/a.png', 'fileId': '123', 'url': 'https://ik.imagekit.io/account/pinterest/a.png'}
            with patch.object(ik, 'api', side_effect=[[], asset]), patch.object(ik, 'verify_media', side_effect=ik.ServiceError('offline')):
                with self.assertRaises(ik.ServiceError):
                    ik.upload_image(path, '/pinterest/', 'a.png', 'secret', receipt=receipt)
            self.assertEqual(json.loads(receipt.read_text())['fileId'], '123')
            with patch.object(ik, 'api') as api, patch.object(ik, 'verify_media', return_value={'media_verified_at': 'now'}):
                ik.upload_image(path, '/pinterest/', 'a.png', 'secret', receipt=receipt)
                api.assert_not_called()

    def test_wrong_path_and_missing_media_rejected(self):
        for asset in ({'filePath': '/wrong/a.png', 'fileId': '1', 'url': 'https://example.com/a.png'}, {'filePath': '/pinterest/a.png', 'fileId': '1'}):
            with self.assertRaises(ik.ServiceError):
                ik.validate_asset(asset, '/pinterest/a.png')

    def test_multipart_disables_overwrites_and_suffixes(self):
        body, _ = ik.multipart(b'bytes', '/pinterest/', 'a.png')
        for field in ('overwriteFile', 'useUniqueFileName', 'isPrivateFile'):
            self.assertIn(('name="' + field + '"\r\n\r\nfalse').encode(), body)

    def test_redirect_handler_never_forwards_auth(self):
        self.assertIsNone(ik.NoRedirect().redirect_request(None, None, 302, '', {}, 'https://evil.com'))

    def test_api_error_redacts_response_and_key(self):
        from urllib.error import HTTPError
        with patch.object(ik, 'build_opener') as opener:
            opener.return_value.open.side_effect = HTTPError(ik.UPLOAD_URL, 302, 'secret', {}, None)
            with self.assertRaises(ik.ServiceError) as error:
                ik.api(ik.UPLOAD_URL, 'secret', b'data')
            self.assertEqual(str(error.exception), 'ImageKit HTTP status 302')

    def test_interrupted_receipt_write_reconciles_without_second_upload(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'a.png'
            path.write_bytes(b'image')
            receipt = Path(folder) / 'receipt.json'
            asset = {'filePath': '/pinterest/a.png', 'fileId': '123', 'url': 'https://ik.imagekit.io/account/pinterest/a.png'}
            with patch.object(ik, 'api', side_effect=[[], asset]), patch.object(ik.json, 'dump', side_effect=OSError('interrupted')):
                with self.assertRaises(OSError):
                    ik.upload_image(path, '/pinterest/', 'a.png', 'secret', receipt=receipt)
            self.assertFalse(receipt.exists())
            with patch.object(ik, 'api', return_value=[asset]) as api, patch.object(ik, 'verify_media', return_value={'media_verified_at': 'now'}):
                ik.upload_image(path, '/pinterest/', 'a.png', 'secret', receipt=receipt)
                self.assertEqual(api.call_count, 1)
                self.assertTrue(api.call_args.args[0].startswith(ik.LIST_URL))
            self.assertEqual(json.loads(receipt.read_text())['fileId'], '123')

    def test_receipt_publication_never_overwrites_existing(self):
        with tempfile.TemporaryDirectory() as folder:
            receipt = Path(folder) / 'receipt.json'
            ik.save_receipt(receipt, {'fileId': 'first'})
            with self.assertRaises(FileExistsError):
                ik.save_receipt(receipt, {'fileId': 'second'})
            self.assertEqual(json.loads(receipt.read_text())['fileId'], 'first')


if __name__ == '__main__':
    unittest.main()
