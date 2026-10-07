import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pinterest_batch as batch
import pinterest_services as services
import pinterest_export as export


def fixture_plan(pin):
    return {
        'kind': pin['kind'], 'slot': pin['slot'],
        'audience_problem': f'Fixture audience problem {pin["pin_id"]}',
        'search_intent': f'Fixture search intent {pin["pin_id"]}',
        'supported_promise': f'Fixture supported promise {pin["pin_id"]}',
        'hook': f'Fixture hook {pin["pin_id"]}',
        'visual_concept': f'Fixture visual concept {pin["pin_id"]}',
        'evidence': 'https://example.com/source',
    }


class ExportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.approvals = self.root / 'approved.md'
        self.approved_url = batch.CAMPAIGN_PRODUCTS['ElevenLabs']['primary_url']
        self.approvals.write_text('- ' + self.approved_url + '\n')
        manifest = batch.init_batch('pilot', self.root, self.approvals, pilot=True)
        self.directory = self.root / 'pilot'
        (self.directory / 'image.png').write_bytes(b'network verification fixture')
        for pin in manifest['pins']:
            (self.directory / (pin['pin_id'] + '.png')).write_bytes(('image fixture ' + pin['pin_id']).encode())
            values = {
                'title': 'Voiceover planning ' + pin['pin_id'], 'description': '#ad Affiliate link. Plan your narration ' + pin['pin_id'],
                'keywords': ['narration'],
                'source_url': 'https://elevenlabs.io/', 'source_checked_at': '2026-09-17T10:00:00Z',
                'creative_plan': fixture_plan(pin),
                'image_path': pin['pin_id'] + '.png', 'media_url': 'https://ik.imagekit.io/test/' + pin['pin_id'] + '.png',
                'remote_file_id': pin['pin_id'], 'short_url': 'https://justonemedia.short.gy/' + pin['pin_id'],
                'short_link_id': 'example',
            }
            candidate = dict(pin, **values)
            values['review_evidence'] = batch.review_evidence_payload(candidate, self.directory, 'fixture-reviewer', '2026-09-17T10:00:00Z')
            values['reviewed'] = True
            with patch.object(batch, 'check_short_url'):
                batch.record_pin(self.directory, pin['pin_id'], values, self.approvals)

    def test_live_failure_blocks_export_and_preserves_batch(self):
        with patch.object(services, 'verify_media', side_effect=services.ServiceError('Media unavailable')):
            with self.assertRaisesRegex(batch.BatchError, 'BLOCKED'):
                export.prepare_export(self.directory, self.approvals)
        self.assertEqual([], list(self.directory.glob('*.csv')))
        self.assertEqual('blocked', batch.load_manifest(self.directory)['state'])
        self.assertEqual(10, len(batch.load_manifest(self.directory)['pins']))

    def test_partial_survivors_weave_after_middle_promotion_failure_and_allow_single_kind(self):
        pins = [
            {'pin_id': 'g1', 'kind': 'guide'}, {'pin_id': 'p1', 'kind': 'promotion'},
            {'pin_id': 'g2', 'kind': 'guide'}, {'pin_id': 'p2', 'kind': 'promotion'},
        ]
        survivors = [pins[0], pins[2], pins[3]]
        self.assertEqual(['guide', 'promotion', 'guide'], [pin['kind'] for pin in batch.weave_export_pins(survivors)])
        self.assertEqual(['g1', 'g2'], [pin['pin_id'] for pin in batch.weave_export_pins([pins[0], pins[2]])])

    def test_one_pin_live_media_failure_exports_other_nine_as_partial(self):
        pins = batch.load_manifest(self.directory)['pins']
        failed_id = pins[0]['pin_id']

        def media(url, local=None):
            if Path(local).stem == failed_id:
                raise services.ServiceError('fixture media failure')
            return {'media_verified_at': '2026-09-18T10:00:00Z'}

        with patch.object(services, 'verify_media', side_effect=media), patch.object(
            services, 'verify_link', return_value={'link_verified_at': '2026-09-18T10:00:00Z'}
        ) as link_check:
            result = export.prepare_export(self.directory, self.approvals)
        self.assertEqual('READY_PARTIAL', result['status'])
        self.assertEqual(9, result['rows'])
        self.assertEqual(9, link_check.call_count)
        saved = batch.load_manifest(self.directory)
        failed = next(pin for pin in saved['pins'] if pin['pin_id'] == failed_id)
        self.assertEqual('omitted', failed['outcome'])
        self.assertEqual('media verification failed', failed['verification_failure'])
        self.assertNotIn('media_verified_at', failed)
        with Path(result['path']).open(newline='', encoding='utf-8') as stream:
            self.assertEqual(9, len(list(csv.reader(stream))) - 1)

    def test_one_pin_live_link_failure_exports_other_nine_as_partial(self):
        pins = batch.load_manifest(self.directory)['pins']
        failed_id = pins[0]['pin_id']

        def link(url, original):
            if failed_id in url:
                raise services.ServiceError('fixture link failure')
            return {'link_verified_at': '2026-09-18T10:00:00Z'}

        with patch.object(services, 'verify_media', return_value={'media_verified_at': '2026-09-18T10:00:00Z'}), patch.object(
            services, 'verify_link', side_effect=link
        ) as link_check:
            result = export.prepare_export(self.directory, self.approvals)
        self.assertEqual('READY_PARTIAL', result['status'])
        self.assertEqual(9, result['rows'])
        self.assertEqual(10, link_check.call_count)
        saved = batch.load_manifest(self.directory)
        failed = next(pin for pin in saved['pins'] if pin['pin_id'] == failed_id)
        self.assertEqual('omitted', failed['outcome'])
        self.assertEqual('link verification failed', failed['verification_failure'])
        self.assertNotIn('link_verified_at', failed)

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
        self.assertEqual({self.approved_url}, {original for _, original in checked_links})
        self.assertEqual(10, result['rows'])
        self.assertEqual('READY_FULL', result['status'])
        self.assertTrue(Path(result['path']).exists())

    def test_partial_export_reservation_import_and_omission_closure(self):
        pins = batch.load_manifest(self.directory)['pins']
        for pin in pins[2:]:
            batch.record_pin(self.directory, pin['pin_id'], {'reviewed': False}, self.approvals)

        def verify(manifest, directory):
            self.assertEqual(2, len(manifest['pins']))
            for pin in manifest['pins']:
                pin['media_verified_at'] = '2026-09-18T10:00:00Z'
                pin['link_verified_at'] = '2026-09-18T10:00:00Z'

        result = batch.export_batch(self.directory, self.approvals, verify_pins=verify)
        self.assertEqual('READY_PARTIAL', result['status'])
        self.assertEqual(2, result['rows'])
        omitted = batch.load_manifest(self.directory)['pins'][2:]
        self.assertEqual({'omitted'}, {pin.get('outcome') for pin in omitted})
        self.assertTrue(all(pin.get('omission_reason') for pin in omitted))
        with Path(result['path']).open(newline='', encoding='utf-8') as stream:
            reader = csv.reader(stream)
            self.assertEqual(batch.HEADERS, next(reader))
            self.assertEqual(2, len(list(reader)))
        with self.assertRaisesRegex(batch.BatchError, 'import outcome'):
            batch.export_batch(self.directory, self.approvals, verify_pins=verify)

        reservation = batch.load_manifest(self.directory)['reservations'][-1]
        outcomes = {pin_id: 'omitted' for pin_id in reservation['pin_ids']}
        with self.assertRaisesRegex(batch.BatchError, 'whole-export'):
            batch.import_outcome(self.directory, result['reservation_id'], outcomes)
        batch.cancel_export(self.directory, result['reservation_id'])
        manifest = batch.load_manifest(self.directory)
        self.assertEqual('cancelled', manifest['reservations'][-1]['status'])
        self.assertEqual('CANCELLED', manifest['reservations'][-1]['lifecycle'])

    def test_zero_passing_pins_are_blocked(self):
        for pin in batch.load_manifest(self.directory)['pins']:
            batch.record_pin(self.directory, pin['pin_id'], {'reviewed': False}, self.approvals)
        with self.assertRaisesRegex(batch.BatchError, 'BLOCKED'):
            batch.export_batch(self.directory, self.approvals, verify_pins=lambda manifest, directory: None)
        self.assertEqual('blocked', batch.load_manifest(self.directory)['state'])
        self.assertEqual([], list(self.directory.glob('*.csv')))

    def test_fixture_mocked_100_pin_full_export_is_dry_run(self):
        fixture_root = self.root / 'full-fixture'
        fixture_root.mkdir()
        approved_urls = [item['primary_url'] for item in batch.CAMPAIGN_PRODUCTS.values()]
        approved_file = fixture_root / 'approved.md'
        approved_file.write_text(''.join('- ' + url + '\n' for url in approved_urls), encoding='utf-8')
        manifest = batch.init_batch('fixture-100', fixture_root, approved_file, batch_size=100)
        directory = fixture_root / 'fixture-100'
        self.assertEqual(100, len(manifest['pins']))

        for pin in manifest['pins']:
            pin_id = pin['pin_id']
            image_name = f'{pin_id}.png'
            (directory / image_name).write_bytes(('fixture image for ' + pin_id).encode())
            values = {
                'title': f'{pin["product"]} workflow guide {pin["slot"]}',
                'description': f'#ad Affiliate link. Evaluate a {pin["product"]} workflow for task {pin_id}.',
                'keywords': ['workflow', pin['product'].lower()],
                'source_url': f'https://example.com/source/{pin_id}',
                'source_checked_at': '2026-10-07T10:00:00Z',
                'creative_plan': fixture_plan(pin),
                'image_path': image_name,
                'media_url': f'https://ik.imagekit.io/fixture/{pin_id}.png',
                'remote_file_id': f'file-{pin_id}',
                'short_url': f'https://justonemedia.short.gy/{pin_id}',
                'short_link_id': f'link-{pin_id}',
            }
            candidate = dict(pin, **values)
            values['review_evidence'] = batch.review_evidence_payload(candidate, directory, 'fixture-reviewer', '2026-10-07T10:00:00Z')
            values['reviewed'] = True
            with patch.object(batch, 'check_short_url'):
                batch.record_pin(directory, pin_id, values, approved_file)

        checked_ids = []

        def mocked_verification(export_manifest, export_directory):
            self.assertEqual(100, len(export_manifest['pins']))
            for pin in export_manifest['pins']:
                checked_ids.append(pin['pin_id'])
                pin['media_verified_at'] = '2026-10-07T10:30:00Z'
                pin['link_verified_at'] = '2026-10-07T10:30:00Z'

        result = batch.export_batch(directory, approved_file, verify_pins=mocked_verification)
        self.assertEqual('READY_FULL', result['status'])
        self.assertEqual(100, result['rows'])
        self.assertEqual(100, len(set(checked_ids)))

        saved = batch.load_manifest(directory)
        self.assertEqual(100, len({pin['pin_id'] for pin in saved['pins']}))
        self.assertEqual(100, len({pin['short_url'] for pin in saved['pins']}))
        self.assertEqual(100, len({pin['remote_file_id'] for pin in saved['pins']}))
        with Path(result['path']).open(newline='', encoding='utf-8') as stream:
            reader = csv.DictReader(stream)
            rows = list(reader)
        self.assertEqual(batch.HEADERS, reader.fieldnames)
        self.assertEqual(100, len(rows))
        self.assertEqual({pin['short_url'] for pin in saved['pins']}, {row['Link'] for row in rows})
        self.assertEqual({pin['media_url'] for pin in saved['pins']}, {row['Media URL'] for row in rows})

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
