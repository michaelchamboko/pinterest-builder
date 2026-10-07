import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pinterest_batch as batch
import pinterest_services as services
import pinterest_export as export


class ExportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.approvals = self.root / 'approved.md'
        self.approvals.write_text('- https://try.elevenlabs.io/example\n')
        manifest = batch.init_batch('pilot', self.root, self.approvals, pilot=True)
        self.directory = self.root / 'pilot'
        (self.directory / 'image.png').write_bytes(b'network verification fixture')
        for pin in manifest['pins']:
            (self.directory / (pin['pin_id'] + '.png')).write_bytes(b'image fixture')
            batch.record_pin(self.directory, pin['pin_id'], {
                'title': 'Voiceover planning ' + pin['pin_id'], 'description': '#ad Affiliate link. Plan your narration ' + pin['pin_id'],
                'keywords': ['narration'], 'reviewed': True,
                'source_url': 'https://elevenlabs.io/', 'source_checked_at': '2026-09-17T10:00:00Z',
                'image_path': pin['pin_id'] + '.png', 'media_url': 'https://ik.imagekit.io/test/' + pin['pin_id'] + '.png',
                'remote_file_id': pin['pin_id'], 'short_url': 'https://justonemedia.short.gy/' + pin['pin_id'],
                'short_link_id': 'example', 'media_verified_at': '2026-09-17T10:00:00Z',
                'link_verified_at': '2026-09-17T10:00:00Z',
            }, self.approvals)

    def test_live_failure_blocks_export_and_preserves_batch(self):
        with patch.object(services, 'verify_media', side_effect=services.ServiceError('Media unavailable')):
            with self.assertRaises(services.ServiceError):
                export.prepare_export(self.directory, self.approvals)
        self.assertEqual([], list(self.directory.glob('*.csv')))
        self.assertEqual('blocked', batch.load_manifest(self.directory)['state'])
        self.assertEqual(10, len(batch.load_manifest(self.directory)['pins']))

    def test_live_checks_cover_every_media_and_preserve_exact_original(self):
        checked_media = []
        checked_links = []
        def media(url, local=None):
            checked_media.append((url, Path(local).name))
            return {'media_verified_at': '2026-09-18T10:00:00Z'}
        def link(url, original):
            checked_links.append((url, original))
            return {'link_verified_at': '2026-09-18T10:00:00Z'}
        with patch.object(services, 'verify_media', side_effect=media), patch.object(services, 'verify_link', side_effect=link):
            result = export.prepare_export(self.directory, self.approvals)
        self.assertEqual(10, len(checked_media))
        self.assertEqual(10, len(checked_links))
        self.assertEqual({'https://try.elevenlabs.io/example'}, {original for _, original in checked_links})
        self.assertEqual(10, result['rows'])
        self.assertTrue(Path(result['path']).exists())

    def test_revocation_stops_before_any_network_request(self):
        self.approvals.write_text('- https://try.elevenlabs.io/different\n')
        with patch.object(services, 'verify_media', side_effect=AssertionError('Network must not run')):
            with self.assertRaises(batch.BatchError):
                export.prepare_export(self.directory, self.approvals)

    def test_concurrent_edit_cannot_receive_old_verification(self):
        pin = batch.load_manifest(self.directory)['pins'][0]
        def media(url, local=None):
            batch.record_pin(self.directory, pin['pin_id'], {
                'media_url': 'https://ik.imagekit.io/test/unchecked.png',
                'reviewed': True,
            }, self.approvals)
            return {'media_verified_at': '2026-09-18T10:00:00Z'}
        with patch.object(services, 'verify_media', side_effect=media), patch.object(services, 'verify_link', return_value={'link_verified_at': '2026-09-18T10:00:00Z'}):
            with self.assertRaises(batch.BatchError):
                export.prepare_export(self.directory, self.approvals)
        self.assertEqual([], list(self.directory.glob('*.csv')))
        self.assertEqual(pin['media_url'], batch.load_manifest(self.directory)['pins'][0]['media_url'])


if __name__ == '__main__':
    unittest.main()
