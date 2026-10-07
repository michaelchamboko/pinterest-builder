import csv
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pinterest_batch as b


class BatchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.approved = self.root / 'approved.md'
        self.urls = ['https://' + host + '/test' for host in b.VENDORS]
        self.urls.insert(8, 'https://get.datahawk.co/second')
        self.write_urls(self.urls)

    def write_urls(self, urls):
        self.approved.write_text('# Approved\n<!-- comment\nignored\n-->\n' + '\n'.join('- ' + u for u in urls), encoding='utf-8')

    def init(self, pilot=False):
        return b.init_batch('test', self.root / 'batches', self.approved, pilot)

    @property
    def directory(self):
        return self.root / 'batches/test'

    def export(self, now=None, verify_pins=None):
        return b.export_batch(self.directory, self.approved, now, verify_pins=verify_pins or (lambda manifest, directory: None))

    def complete(self):
        manifest = self.init(True)
        image = self.directory / 'image.png'
        image.write_bytes(b'image-validation-owned-by-integration')
        for pin in manifest['pins']:
            (self.directory / (pin['pin_id'] + '.png')).write_bytes(b'image fixture')
            b.record_pin(self.directory, pin['pin_id'], {
                'title': f'A "title", with comma {pin["slot"]}', 'description': f'Text {pin["slot"]}\nAffiliate disclosure: I may earn a commission.',
                'keywords': ['AI', 'voice'], 'reviewed': True,
                'source_url': 'https://elevenlabs.io', 'source_checked_at': '2026-09-17T10:00:00Z',
                'image_path': pin['pin_id'] + '.png', 'media_url': 'https://ik.imagekit.io/' + pin['pin_id'] + '.png',
                'remote_file_id': pin['pin_id'], 'short_url': 'https://justonemedia.short.gy/' + pin['pin_id'],
                'short_link_id': 'link-id', 'media_verified_at': '2026-09-17T10:00:00Z',
                'link_verified_at': '2026-09-17T10:00:00Z',
            }, self.approved)
            b.record_pin(self.directory, pin['pin_id'], {'media_verified_at': '2026-09-17T10:00:00Z', 'link_verified_at': '2026-09-17T10:00:00Z'}, self.approved)

    def test_record_accepts_allowlisted_alternate_short_domain(self):
        manifest = self.init(True)
        image = self.directory / 'image.png'
        image.write_bytes(b'image-validation-owned-by-integration')
        pin = manifest['pins'][0]
        b.record_pin(self.directory, pin['pin_id'], {
            'title': 'Title', 'description': 'Text', 'keywords': ['AI'], 'reviewed': True,
            'source_url': 'https://elevenlabs.io', 'source_checked_at': '2026-09-17T10:00:00Z',
            'image_path': 'image.png', 'media_url': 'https://ik.imagekit.io/example.png',
            'remote_file_id': 'file-id', 'short_url': 'https://justonemedia.short.gy/test',
            'short_link_id': 'link-id', 'media_verified_at': '2026-09-17T10:00:00Z',
            'link_verified_at': '2026-09-17T10:00:00Z',
        }, self.approved)

    def test_full_pilot_resume_and_interleaving(self):
        manifest = self.init()
        self.assertEqual(150, len(manifest['pins']))
        self.assertEqual(20, sum(p['vendor'] == 'DataHawk' for p in manifest['pins']))
        self.assertTrue(all(a['vendor'] != c['vendor'] for a, c in zip(manifest['pins'], manifest['pins'][1:])))
        p = manifest['pins'][0]
        b.record_pin(self.directory, p['pin_id'], {'title': 'Retained'}, self.approved)
        self.assertEqual('Retained', self.init()['pins'][0]['title'])
        with self.assertRaises(b.BatchError):
            self.init(True)

    def test_current_approved_source_parses_and_maps_new_vendors(self):
        urls = b.parse_approved_urls()
        self.assertIn('https://join.glideapps.com/9r1tcciij70r', urls)
        self.assertIn('https://manychat.partnerlinks.io/vettedsaasblueprint', urls)

        manifest = self.init()
        mapped = {pin['vendor']: pin['board'] for pin in manifest['pins']}
        self.assertEqual('AI Tools & Automation', mapped['Glide'])
        self.assertEqual('Business Growth Strategies', mapped['ManyChat'])

    def test_pilot(self):
        self.assertEqual(10, len(self.init(True)['pins']))

    def test_malformed_manifest_fails_safely_for_pending_and_export(self):
        import copy
        import json
        original = self.init(True)
        malformed = [None, [], {}, dict(original, pins=None), dict(original, pins=[None]), dict(original, approved_urls=[{}])]
        for field, value in [('slot', '1'), ('slot', True), ('pin_id', []), ('kind', None), ('title', []), ('image_path', ''), ('media_url', {}), ('remote_file_id', ' ')]:
            manifest = copy.deepcopy(original)
            manifest['pins'][0][field] = value
            malformed.append(manifest)
        for field in ('pins', 'approved_urls', 'state', 'exports', 'batch_id'):
            manifest = copy.deepcopy(original)
            del manifest[field]
            malformed.append(manifest)
        for field in ('pin_id', 'affiliate_url', 'slot', 'kind', 'board'):
            manifest = copy.deepcopy(original)
            del manifest['pins'][0][field]
            malformed.append(manifest)
        for manifest in malformed:
            with self.subTest(manifest=manifest):
                (self.directory / 'manifest.json').write_text(json.dumps(manifest))
                for operation in (lambda: b.pending_pins(self.directory), lambda: self.export()):
                    with self.assertRaisesRegex(b.BatchError, 'restore a valid manifest'):
                        operation()
                self.assertEqual([], list(self.directory.glob('*.csv')))
        (self.directory / 'manifest.json').write_text('{"pins": [')
        for operation in (lambda: b.pending_pins(self.directory), lambda: self.export()):
            with self.assertRaisesRegex(b.BatchError, 'restore a valid manifest'):
                operation()

    def test_direct_export_requires_live_verification(self):
        self.complete()
        with self.assertRaisesRegex(b.BatchError, 'Live verification'):
            b.export_batch(self.directory, self.approved)
        with patch('sys.stderr'):
            self.assertEqual(1, b.main(['export', '--batch', 'test']))
        self.assertEqual([], list(self.directory.glob('*.csv')))

    def test_new_legacy_link_rejected_existing_receipt_preserved(self):
        self.complete()
        manifest = b.load_manifest(self.directory)
        pin = manifest['pins'][0]
        legacy = 'https://vettedsaasblueprint.s.gy/legacy'
        with self.assertRaises(b.BatchError):
            b.record_pin(self.directory, pin['pin_id'], {'short_url': legacy}, self.approved)
        pin['short_url'] = legacy
        b.save_manifest(self.directory, manifest)
        self.assertTrue(b.complete_pin(self.directory, pin))
        b.record_pin(self.directory, pin['pin_id'], {'short_url': legacy}, self.approved)
        self.export()

    def test_invalid_plan_or_duplicate_creative_cannot_export(self):
        self.complete()
        original = b.load_manifest(self.directory)
        import copy
        for field in ('short_url', 'title', 'description', 'image_path', 'media_url', 'remote_file_id', 'slot', 'kind', 'pin_id'):
            with self.subTest(field=field):
                manifest = copy.deepcopy(original)
                target = 5 if field == 'kind' else 1
                manifest['pins'][target][field] = manifest['pins'][0][field]
                b.save_manifest(self.directory, manifest)
                with self.assertRaises(b.BatchError):
                    self.export()
                self.assertEqual([], list(self.directory.glob('*.csv')))
                with self.assertRaises(b.BatchError):
                    b.pending_pins(self.directory)
        original['pins'].pop()
        b.save_manifest(self.directory, original)
        with self.assertRaises(b.BatchError):
            self.export()

    def test_approval_fails_closed(self):
        for content in ['', '- http://try.elevenlabs.io/a', '- https://unknown.example/a', '- https://try.elevenlabs.io/a\n- https://try.elevenlabs.io/a', 'unrecognized prose']:
            self.approved.write_text(content, encoding='utf-8')
            with self.assertRaises(b.BatchError):
                b.parse_approved_urls(self.approved)

    def test_incomplete_and_revocation(self):
        manifest = self.init(True)
        with self.assertRaises(b.BatchError):
            self.export()
        self.assertEqual([], list(self.directory.glob('*.csv')))
        self.write_urls([u for u in self.urls if 'elevenlabs' not in u])
        with self.assertRaises(b.BatchError):
            b.record_pin(self.directory, manifest['pins'][0]['pin_id'], {'title': 'No'}, self.approved)

    def test_export_roundtrip_version_dates_and_uploaded_guard(self):
        self.complete()
        now = datetime(2026, 9, 17, 12, 0, tzinfo=timezone.utc)
        first = self.export(now)
        second = self.export(now)
        self.assertNotEqual(first['path'], second['path'])
        with Path(first['path']).open(newline='', encoding='utf-8') as f:
            rows = list(csv.DictReader(f))
        self.assertEqual(b.HEADERS, list(rows[0].keys()))
        self.assertEqual('2026-09-17T12:30:00', rows[0]['Publish Date'])
        self.assertEqual('2026-09-17T13:00:00', rows[1]['Publish Date'])
        for row in rows:
            value = row['Publish Date']
            self.assertRegex(value, r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$')
            self.assertIn(datetime.strptime(value, '%Y-%m-%dT%H:%M:%S').minute, (0, 30))
        self.assertEqual('A "title", with comma 1', rows[0]['Title'])
        self.assertIn('\nAffiliate', rows[0]['Description'])
        self.assertEqual([], b.pending_pins(self.directory))
        b.mark_uploaded(self.directory)
        with self.assertRaises(b.BatchError):
            self.export(now)

    def test_export_dates_align_to_utc_half_hour_after_thirty_minutes(self):
        self.complete()
        exported = self.export(datetime(2026, 10, 7, 7, 19, 35, tzinfo=timezone.utc))
        with Path(exported['path']).open(newline='', encoding='utf-8') as stream:
            rows = list(csv.DictReader(stream))
        self.assertEqual('2026-10-07T08:00:00', rows[0]['Publish Date'])
        self.assertEqual('2026-10-07T08:30:00', rows[1]['Publish Date'])
        self.assertEqual('2026-10-07T09:00:00', rows[2]['Publish Date'])

    def test_export_dates_advance_from_exact_half_hour_boundary(self):
        self.complete()
        exported = self.export(datetime(2026, 10, 7, 7, 30, tzinfo=timezone.utc))
        with Path(exported['path']).open(newline='', encoding='utf-8') as stream:
            rows = list(csv.DictReader(stream))
        self.assertEqual('2026-10-07T08:00:00', rows[0]['Publish Date'])

    def test_record_validation_lock_and_missing_asset(self):
        self.complete()
        pin = b.load_manifest(self.directory)['pins'][0]
        for data in [{'vendor': 'Other'}, {'reviewed': 'true'}, {'title': 'x' * 101}, {'short_url': 'https://evil.test/x'}, {'image_path': '../outside.png'}]:
            with self.assertRaises(b.BatchError):
                b.record_pin(self.directory, pin['pin_id'], data, self.approved)
        lock = self.directory / '.lock'
        lock.write_text('interrupted')
        with self.assertRaisesRegex(b.BatchError, 'lock'):
            b.record_pin(self.directory, pin['pin_id'], {'title': 'No'}, self.approved)
        lock.unlink()
        (self.directory / pin['image_path']).unlink()
        with self.assertRaises(b.BatchError):
            self.export()

    def test_offset_is_converted_to_utc_and_block_stops_work(self):
        self.complete()
        exported = self.export(datetime(2026, 9, 17, 12, tzinfo=timezone(timedelta(hours=2))))
        with Path(exported['path']).open(newline='', encoding='utf-8') as stream:
            self.assertEqual('2026-09-17T10:30:00', list(csv.DictReader(stream))[0]['Publish Date'])
        b.block_batch(self.directory, 'Awaiting review')
        self.assertEqual([], b.pending_pins(self.directory))
        with self.assertRaises(b.BatchError):
            self.export()

    def test_copy_edit_invalidates_review(self):
        self.complete()
        pin = b.load_manifest(self.directory)['pins'][0]
        b.record_pin(self.directory, pin['pin_id'], {'description': 'Changed affiliate disclosure'}, self.approved)
        self.assertFalse(b.load_manifest(self.directory)['pins'][0]['reviewed'])
        with self.assertRaises(b.BatchError):
            self.export()

    def test_media_and_link_edits_invalidate_evidence(self):
        self.complete()
        pin_id = b.load_manifest(self.directory)['pins'][0]['pin_id']
        b.record_pin(self.directory, pin_id, {'media_url': 'https://ik.imagekit.io/new.png', 'short_url': 'https://justonemedia.short.gy/new'}, self.approved)
        pin = b.load_manifest(self.directory)['pins'][0]
        self.assertNotIn('media_verified_at', pin)
        self.assertNotIn('link_verified_at', pin)

    def test_export_edit_requires_new_export_before_upload(self):
        self.complete()
        self.export()
        pin_id = b.load_manifest(self.directory)['pins'][0]['pin_id']
        b.record_pin(self.directory, pin_id, {'title': 'Changed', 'reviewed': True}, self.approved)
        manifest = b.load_manifest(self.directory)
        self.assertEqual('active', manifest['state'])
        self.assertTrue(manifest['exports'][0]['invalidated'])
        with self.assertRaises(b.BatchError):
            b.mark_uploaded(self.directory)
        self.export()
        b.mark_uploaded(self.directory)
        with self.assertRaises(b.BatchError):
            b.block_batch(self.directory, 'Cannot reset uploaded')

    def test_resume_blocked_rechecks_approval(self):
        manifest = self.init(True)
        b.block_batch(self.directory, 'Paused for repair')
        self.assertEqual('active', b.resume_batch(self.directory, self.approved)['state'])
        b.block_batch(self.directory, 'Paused again')
        self.write_urls([u for u in self.urls if 'elevenlabs' not in u])
        with self.assertRaises(b.BatchError):
            b.resume_batch(self.directory, self.approved)
        self.assertEqual(manifest['pins'], b.load_manifest(self.directory)['pins'])

    def test_approval_fragment_rejected(self):
        self.write_urls(['https://try.elevenlabs.io/test#fragment'])
        with self.assertRaises(b.BatchError):
            b.parse_approved_urls(self.approved)

    def test_interrupted_csv_never_appears_as_uploadable_file(self):
        self.complete()
        with patch.object(b.os, 'replace', side_effect=OSError('Interrupted')):
            with self.assertRaises(OSError):
                self.export()
        self.assertEqual([], list(self.directory.glob('*.csv')))
        self.assertEqual([], b.load_manifest(self.directory)['exports'])
        self.assertEqual('active', b.load_manifest(self.directory)['state'])
        self.assertTrue(Path(self.export()['path']).is_file())

    def test_replacement_evidence_is_invalidated_even_when_resubmitted(self):
        self.complete()
        pin_id = b.load_manifest(self.directory)['pins'][0]['pin_id']
        fresh = '2026-09-17T11:00:00Z'
        b.record_pin(self.directory, pin_id, {'media_url': 'https://ik.imagekit.io/new.png', 'media_verified_at': fresh, 'short_url': 'https://justonemedia.short.gy/new', 'link_verified_at': fresh}, self.approved)
        pin = b.load_manifest(self.directory)['pins'][0]
        self.assertNotIn('media_verified_at', pin)
        self.assertNotIn('link_verified_at', pin)

    def test_live_export_callback_holds_lock_and_saves_evidence(self):
        self.complete()
        def verify(manifest, directory):
            with self.assertRaisesRegex(b.BatchError, 'lock'):
                b.record_pin(directory, manifest['pins'][0]['pin_id'], {'title': 'Race'}, self.approved)
            manifest['pins'][0]['media_verified_at'] = '2026-09-17T11:00:00Z'
        self.export(verify_pins=verify)
        self.assertEqual('2026-09-17T11:00:00Z', b.load_manifest(self.directory)['pins'][0]['media_verified_at'])

    def test_live_export_revocation_blocks_and_invalidates_previous_export(self):
        self.complete()
        self.export()
        def revoke(manifest, directory):
            self.write_urls([u for u in self.urls if 'elevenlabs' not in u])
        with self.assertRaises(b.BatchError):
            self.export(verify_pins=revoke)
        manifest = b.load_manifest(self.directory)
        self.assertEqual('blocked', manifest['state'])
        self.assertTrue(manifest['exports'][0]['invalidated'])
        self.assertEqual(1, len(list(self.directory.glob('*.csv'))))


if __name__ == '__main__':
    unittest.main()
