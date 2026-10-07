import csv
import json
import tempfile
import unittest
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pinterest_batch as b


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


class BatchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.approved = self.root / 'approved.md'
        self.urls = [config['primary_url'] for config in b.CAMPAIGN_PRODUCTS.values()]
        self.urls.extend('https://' + host + '/test' for host in b.VENDORS)
        self.urls.insert(8, 'https://get.datahawk.co/second')
        self.urls.append('https://manychat.partnerlinks.io/secondary')
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
            (self.directory / (pin['pin_id'] + '.png')).write_bytes(('image fixture ' + pin['pin_id']).encode())
            values = {
                'title': f'A "title", with comma {pin["slot"]}', 'description': f'Text {pin["slot"]}\nAffiliate disclosure: I may earn a commission.',
                'keywords': ['AI', 'voice'],
                'source_url': 'https://elevenlabs.io', 'source_checked_at': '2026-09-17T10:00:00Z',
                'creative_plan': fixture_plan(pin),
                'image_path': pin['pin_id'] + '.png', 'media_url': 'https://ik.imagekit.io/' + pin['pin_id'] + '.png',
                'remote_file_id': pin['pin_id'], 'short_url': 'https://justonemedia.short.gy/' + pin['pin_id'],
                'short_link_id': 'link-id',
            }
            candidate = dict(pin, **values)
            values['review_evidence'] = b.review_evidence_payload(candidate, self.directory, 'fixture-reviewer', '2026-09-17T10:00:00Z')
            values['reviewed'] = True
            with patch.object(b, 'check_short_url'):
                b.record_pin(self.directory, pin['pin_id'], values, self.approved)
            b.record_pin(self.directory, pin['pin_id'], {'media_verified_at': '2026-09-17T10:00:00Z', 'link_verified_at': '2026-09-17T10:00:00Z'}, self.approved)

    def reapprove(self, pin):
        evidence = b.review_evidence_payload(pin, self.directory, 'fixture-reviewer', '2026-09-17T11:00:00Z')
        b.record_pin(self.directory, pin['pin_id'], {'review_evidence': evidence, 'reviewed': True}, self.approved)

    def test_record_accepts_allowlisted_alternate_short_domain(self):
        manifest = self.init(True)
        image = self.directory / 'image.png'
        image.write_bytes(b'image-validation-owned-by-integration')
        pin = manifest['pins'][0]
        values = {
            'title': 'Title', 'description': 'Text', 'keywords': ['AI'],
            'source_url': 'https://elevenlabs.io', 'source_checked_at': '2026-09-17T10:00:00Z',
            'creative_plan': fixture_plan(pin),
            'image_path': 'image.png', 'media_url': 'https://ik.imagekit.io/example.png',
            'remote_file_id': 'file-id', 'short_url': 'https://justonemedia.short.gy/test',
            'short_link_id': 'link-id',
        }
        candidate = dict(pin, **values)
        values['review_evidence'] = b.review_evidence_payload(candidate, self.directory, 'fixture-reviewer', '2026-09-17T10:00:00Z')
        values['reviewed'] = True
        with patch.object(b, 'check_short_url'):
            b.record_pin(self.directory, pin['pin_id'], values, self.approved)

    def test_full_pilot_resume_and_interleaving(self):
        manifest = self.init()
        self.assertEqual(100, len(manifest['pins']))
        self.assertEqual(10, sum(p['vendor'] == 'DataHawk' for p in manifest['pins']))
        self.assertTrue(all(a['vendor'] != c['vendor'] for a, c in zip(manifest['pins'], manifest['pins'][1:])))
        p = manifest['pins'][0]
        b.record_pin(self.directory, p['pin_id'], {'title': 'Retained'}, self.approved)
        self.assertEqual('Retained', self.init()['pins'][0]['title'])
        with self.assertRaises(b.BatchError):
            self.init(True)

    def test_current_approved_source_parses_and_maps_new_vendors(self):
        urls = b.parse_approved_urls(self.approved)
        self.assertIn('https://join.glideapps.com/9r1tcciij70r', urls)
        self.assertIn('https://manychat.partnerlinks.io/vettedsaasblueprint', urls)

        manifest = self.init()
        mapped = {pin['vendor']: pin['board'] for pin in manifest['pins']}
        self.assertEqual('AI Tools & Automation', mapped['Glide'])
        self.assertEqual('Business Growth Strategies', mapped['Manychat'])

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
        b.cancel_export(self.directory, first['reservation_id'])
        pins = b.load_manifest(self.directory)['pins']
        for pin in pins:
            b.record_pin(self.directory, pin['pin_id'], {'title': pin['title'] + ' revised', 'reviewed': False}, self.approved)
            current = next(item for item in b.load_manifest(self.directory)['pins'] if item['pin_id'] == pin['pin_id'])
            self.reapprove(current)
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

    def test_schedule_has_twenty_johannesburg_slots_and_weekend_rollover(self):
        anchor = datetime(2026, 10, 9, 15, 0, tzinfo=timezone.utc)  # Friday 17:00 local
        slots = b.plan_schedule_slots(anchor, 21, self.root / 'batches')
        self.assertEqual('2026-10-09T15:30:00', slots[0])
        self.assertEqual('2026-10-09T16:00:00', slots[1])
        self.assertEqual('2026-10-09T16:30:00', slots[2])  # Friday 18:30 local
        self.assertEqual('2026-10-10T07:00:00', slots[3])  # Saturday 09:00 local
        self.assertEqual('2026-10-10T15:30:00', slots[-1])  # Saturday 17:30 local

    def test_schedule_skips_reserved_and_consumed_slots_but_reuses_cancelled(self):
        root = self.root / 'batches'
        prior = root / 'prior'
        prior.mkdir(parents=True)
        occupied = '2026-10-07T07:00:00'
        consumed = '2026-10-07T07:30:00'
        released = '2026-10-07T08:00:00'
        (prior / 'manifest.json').write_text(json.dumps({
            'reservations': [
                {'status': 'exported', 'schedule_slots': [occupied]},
                {'status': 'uploaded', 'schedule_slots': [consumed]},
                {'status': 'cancelled', 'schedule_slots': [released]},
            ],
            'exports': [],
        }), encoding='utf-8')
        slots = b.plan_schedule_slots(datetime(2026, 10, 7, 6, 30, tzinfo=timezone.utc), 2, root)
        self.assertEqual([released, '2026-10-07T08:30:00'], slots)

    def test_schedule_lock_failure_rolls_back_unallocated_reservation(self):
        self.complete()
        lock_directory = self.root / 'batches/.schedule-lock'
        lock_directory.mkdir(parents=True)
        (lock_directory / '.lock').write_text('busy', encoding='utf-8')
        with self.assertRaisesRegex(b.BatchError, 'lock exists'):
            self.export()
        self.assertEqual([], b.load_manifest(self.directory)['reservations'])

    def test_record_validation_lock_and_missing_asset(self):
        self.complete()
        pin = b.load_manifest(self.directory)['pins'][0]
        for data in [{'vendor': 'Other'}, {'reviewed': 'true'}, {'title': 'x' * 101}, {'short_url': 'https://evil.test/x'}, {'image_path': '../outside.png'}]:
            with self.subTest(data=data), self.assertRaises(b.BatchError):
                b.record_pin(self.directory, pin['pin_id'], data, self.approved)
        lock = self.directory / '.lock'
        lock.write_text('interrupted')
        with self.assertRaisesRegex(b.BatchError, 'lock'):
            b.record_pin(self.directory, pin['pin_id'], {'title': 'No'}, self.approved)
        lock.unlink()
        missing_title = pin['title']
        (self.directory / pin['image_path']).unlink()
        exported = self.export()
        self.assertEqual('READY_PARTIAL', exported['status'])
        self.assertEqual(9, exported['rows'])
        with Path(exported['path']).open(newline='', encoding='utf-8') as stream:
            rows = list(csv.DictReader(stream))
        self.assertEqual(9, len(rows))
        self.assertNotIn(missing_title, {row['Title'] for row in rows})

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
        result = self.export()
        self.assertEqual('READY_PARTIAL', result['status'])

    def test_media_and_link_edits_invalidate_evidence(self):
        self.complete()
        pin_id = b.load_manifest(self.directory)['pins'][0]['pin_id']
        b.record_pin(self.directory, pin_id, {'media_url': 'https://ik.imagekit.io/new.png', 'short_url': 'https://justonemedia.short.gy/new'}, self.approved)
        pin = b.load_manifest(self.directory)['pins'][0]
        self.assertNotIn('media_verified_at', pin)
        self.assertNotIn('link_verified_at', pin)

    def test_export_edit_requires_new_export_before_upload(self):
        self.complete()
        first = self.export()
        pin_id = b.load_manifest(self.directory)['pins'][0]['pin_id']
        b.record_pin(self.directory, pin_id, {'title': 'Changed', 'reviewed': False}, self.approved)
        manifest = b.load_manifest(self.directory)
        self.assertEqual('active', manifest['state'])
        self.assertTrue(manifest['exports'][0]['invalidated'])
        reservation = manifest['reservations'][-1]
        b.cancel_export(self.directory, reservation['reservation_id'])
        for pin in b.load_manifest(self.directory)['pins']:
            b.record_pin(self.directory, pin['pin_id'], {'title': pin['title'] + ' retry', 'reviewed': False}, self.approved)
            current = next(item for item in b.load_manifest(self.directory)['pins'] if item['pin_id'] == pin['pin_id'])
            self.reapprove(current)
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
        first = self.export()
        manifest = b.load_manifest(self.directory)
        reservation = manifest['reservations'][-1]
        b.cancel_export(self.directory, first['reservation_id'])
        for pin in b.load_manifest(self.directory)['pins']:
            b.record_pin(self.directory, pin['pin_id'], {'title': pin['title'] + ' retry', 'reviewed': False}, self.approved)
            current = next(item for item in b.load_manifest(self.directory)['pins'] if item['pin_id'] == pin['pin_id'])
            self.reapprove(current)
        def revoke(manifest, directory):
            self.write_urls([u for u in self.urls if 'elevenlabs' not in u])
        with self.assertRaises(b.BatchError):
            self.export(verify_pins=revoke)
        manifest = b.load_manifest(self.directory)
        self.assertEqual('blocked', manifest['state'])
        self.assertTrue(manifest['exports'][0]['invalidated'])
        self.assertEqual(1, len(list(self.directory.glob('*.csv'))))

    def test_product_allocation_sizes_primary_manychat_url_and_cursor_rotation(self):
        one = b.init_batch('one', self.root / 'batches', self.approved, batch_size=1)
        self.assertEqual(1, len(one['pins']))
        self.assertEqual(2, one['image_attempt_budget'])
        ninety_nine = b.init_batch('ninety-nine', self.root / 'batches', self.approved, batch_size=99)
        counts = Counter(pin['product'] for pin in ninety_nine['pins'])
        self.assertEqual(99, sum(counts.values()))
        self.assertEqual(9, sum(value == 10 for value in counts.values()))
        rotated = b.init_batch('rotated', self.root / 'batches', self.approved, batch_size=99, allocation_cursor=2)
        self.assertNotEqual(counts, Counter(pin['product'] for pin in rotated['pins']))
        full = self.init()
        self.assertEqual(100, len(full['pins']))
        self.assertEqual({10}, set(Counter(pin['product'] for pin in full['pins']).values()))
        manychat = [pin for pin in full['pins'] if pin['product'] == 'Manychat']
        self.assertEqual(10, len(manychat))
        expected = b.CAMPAIGN_PRODUCTS['Manychat']['primary_url']
        self.assertEqual({expected}, {pin['destination_url'] for pin in manychat})
        self.assertEqual({expected}, {pin['affiliate_url'] for pin in manychat})
        self.assertNotIn('https://manychat.partnerlinks.io/secondary', full['approved_urls'])
        with self.assertRaisesRegex(b.BatchError, 'positive integer'):
            b.init_batch('zero', self.root / 'batches', self.approved, batch_size=0)

    def test_allocation_cursor_rotates_automatically_across_normal_runs(self):
        first = b.init_batch('auto-one', self.root / 'auto', self.approved, batch_size=99)
        second = b.init_batch('auto-two', self.root / 'auto', self.approved, batch_size=99)
        first_counts = Counter(pin['product'] for pin in first['pins'])
        second_counts = Counter(pin['product'] for pin in second['pins'])
        self.assertNotEqual(first_counts, second_counts)
        self.assertEqual(1, first['allocation_cursor'])
        self.assertEqual(2, second['allocation_cursor'])
        odd_first = b.init_batch('odd-one', self.root / 'odd', self.approved, batch_size=1)
        odd_second = b.init_batch('odd-two', self.root / 'odd', self.approved, batch_size=1)
        self.assertEqual('guide', odd_first['pins'][0]['kind'])
        self.assertEqual('guide', odd_second['pins'][0]['kind'])

    def test_product_queues_round_robin_and_kinds_alternate(self):
        manifest = b.init_batch('ordered', self.root / 'ordered', self.approved, batch_size=20)
        self.assertEqual(['guide', 'promotion'] * 10, [pin['kind'] for pin in manifest['pins']])
        self.assertEqual(10, len(set(pin['product'] for pin in manifest['pins'][:10])))
        for product in b.CAMPAIGN_PRODUCTS:
            self.assertEqual(1, sum(pin['kind'] == 'guide' for pin in manifest['pins'] if pin['product'] == product))
            self.assertEqual(1, sum(pin['kind'] == 'promotion' for pin in manifest['pins'] if pin['product'] == product))
        default = b.init_batch('ordered-default', self.root / 'ordered', self.approved)
        self.assertEqual(['guide', 'promotion'] * 50, [pin['kind'] for pin in default['pins']])

    def test_confirm_uploaded_and_cancel_export_are_whole_export_transitions(self):
        self.complete()
        exported = self.export(datetime(2026, 10, 7, 7, 0, tzinfo=timezone.utc))
        with self.assertRaisesRegex(b.BatchError, 'whole-export'):
            b.import_outcome(self.directory, exported['reservation_id'], {
                pin['pin_id']: 'uploaded' for pin in b.load_manifest(self.directory)['pins']
            })
        uploaded = b.confirm_uploaded(self.directory, exported['reservation_id'])
        self.assertEqual('uploaded', uploaded['reservations'][-1]['status'])
        self.assertEqual('UPLOADED', uploaded['reservations'][-1]['lifecycle'])

        cancelled_dir = self.root / 'cancelled'
        cancelled_dir.mkdir()
        b.save_manifest(cancelled_dir, {
            'batch_id': 'cancelled', 'state': 'exported', 'pins': [], 'exports': [
                {'reservation_id': 'cancel-me'}],
            'reservations': [{'reservation_id': 'cancel-me', 'status': 'exported', 'schedule_slots': ['2026-10-07T07:00:00']}],
        })
        cancelled = b.cancel_export(cancelled_dir, 'cancel-me')
        self.assertEqual('cancelled', cancelled['reservations'][-1]['status'])
        self.assertEqual('CANCELLED', cancelled['reservations'][-1]['lifecycle'])

    def test_injected_fifteen_board_mapping_is_balanced_and_defaults_stay_verified(self):
        fixture_boards = [f'Fixture Board {n}' for n in range(15)]
        config = {'Carepatron': {'primary_url': b.CAMPAIGN_PRODUCTS['Carepatron']['primary_url'], 'eligible_boards': fixture_boards}}
        manifest = b.init_batch('boards', self.root / 'batches', self.approved, batch_size=100, campaign=config)
        counts = Counter(pin['board'] for pin in manifest['pins'])
        self.assertEqual(15, len(counts))
        self.assertLessEqual(max(counts.values()) - min(counts.values()), 1)
        self.assertEqual({'Productivity & Efficiency'}, set(b.CAMPAIGN_PRODUCTS['Carepatron']['eligible_boards']))

    def test_legacy_migration_snapshots_only_on_explicit_unfinished_migration(self):
        legacy = {'schema_version': 1, 'batch_id': 'legacy', 'mode': 'pilot', 'state': 'active', 'approved_urls': [b.CAMPAIGN_PRODUCTS['ElevenLabs']['primary_url']], 'pins': [], 'exports': []}
        directory = self.root / 'batches/legacy'
        directory.mkdir(parents=True)
        target = directory / 'manifest.json'
        import json
        target.write_text(json.dumps(legacy), encoding='utf-8')
        self.assertEqual(1, b.load_manifest(directory)['schema_version'])
        self.assertFalse((directory / 'manifest.v1.snapshot.json').exists())
        migrated = b.migrate_legacy_batch(directory, self.approved)
        self.assertEqual(b.SCHEMA_VERSION, migrated['schema_version'])
        self.assertEqual(legacy, json.loads((directory / 'manifest.v1.snapshot.json').read_text(encoding='utf-8')))
        finished_dir = self.root / 'batches/finished'
        finished_dir.mkdir(parents=True)
        finished = dict(legacy, batch_id='finished', state='uploaded', exports=[{'version': 1}])
        (finished_dir / 'manifest.json').write_text(json.dumps(finished), encoding='utf-8')
        self.assertEqual('uploaded', b.load_manifest(finished_dir)['state'])
        with self.assertRaisesRegex(b.BatchError, 'unfinished legacy'):
            b.migrate_legacy_batch(finished_dir, self.approved)

    def test_structured_creative_plan_and_review_evidence_hash_assets(self):
        empty = self.init(True)
        self.assertNotIn('creative_plan', empty['pins'][0])
        with self.assertRaisesRegex(b.BatchError, 'creative plan'):
            b.record_image_attempt(self.directory, empty['pins'][0]['pin_id'])
        self.complete()
        saved = b.load_manifest(self.directory)['pins'][0]
        self.assertTrue(b.valid_review(saved, self.directory))
        self.assertEqual('PASS', saved['review_evidence']['verdict'])
        self.assertEqual(64, len(saved['review_evidence']['asset_sha256']))
        (self.directory / saved['image_path']).write_bytes(b'changed image bytes')
        self.assertFalse(b.valid_review(saved, self.directory))

    def test_source_change_invalidates_bound_review(self):
        self.complete()
        pin = b.load_manifest(self.directory)['pins'][0]
        self.assertTrue(b.valid_review(pin, self.directory))
        changed = b.record_pin(self.directory, pin['pin_id'], {'source_url': 'https://example.com/changed'}, self.approved)
        updated = next(item for item in changed['pins'] if item['pin_id'] == pin['pin_id'])
        self.assertIs(updated['reviewed'], False)
        self.assertNotIn('review_evidence', updated)
        self.assertFalse(b.valid_review(updated, self.directory))

    def test_prior_batch_exact_duplicate_is_rejected(self):
        self.complete()
        prior = b.load_manifest(self.directory)['pins'][0]
        newer = b.init_batch('next', self.root / 'batches', self.approved, pilot=True)
        with self.assertRaisesRegex(b.BatchError, 'Duplicate title from prior batch'):
            b.record_pin(self.root / 'batches/next', newer['pins'][0]['pin_id'], {'title': prior['title']}, self.approved)
        self.assertIn('test', newer['history_batches'])

    def test_unreadable_sibling_history_blocks_new_batch(self):
        root = self.root / 'unsafe-history'
        broken = root / 'broken'
        broken.mkdir(parents=True)
        (broken / 'manifest.json').write_text('{invalid', encoding='utf-8')
        with self.assertRaisesRegex(b.BatchError, 'Unreadable batch history'):
            b.init_batch('new', root, self.approved, batch_size=1)

    def test_persistent_attempt_budget_and_three_repairs_per_pin(self):
        manifest = b.init_batch('attempts', self.root / 'batches', self.approved, batch_size=10)
        directory = self.root / 'batches/attempts'
        pin_id = manifest['pins'][0]['pin_id']
        b.record_pin(directory, pin_id, {'creative_plan': fixture_plan(manifest['pins'][0])}, self.approved)
        self.assertEqual(12, manifest['image_attempt_budget'])
        for count in range(1, 5):
            self.assertEqual(count, b.record_image_attempt(directory, pin_id))
            before_failure = b.load_manifest(directory)['pins'][0]
            self.assertNotEqual('omitted', before_failure.get('outcome'))
            failed = b.record_image_failure(directory, pin_id, f'Fixture generation failure {count}')
            if count < 4:
                self.assertNotEqual('omitted', failed.get('outcome'))
            else:
                self.assertEqual('omitted', failed.get('outcome'))
                self.assertEqual('Fixture generation failure 4', failed['omission_reason'])
        with self.assertRaisesRegex(b.BatchError, 'closed to image attempts'):
            b.record_image_attempt(directory, pin_id)
        with self.assertRaisesRegex(b.BatchError, 'closed to image failures'):
            b.record_image_failure(directory, pin_id, 'another failure')
        stored = b.load_manifest(directory)
        self.assertEqual(4, stored['pins'][0]['attempts'])
        self.assertEqual(3, stored['pins'][0]['repair_attempts'])
        self.assertEqual(4, stored['pins'][0]['failed_attempts'])
        self.assertEqual(3, stored['pins'][0]['failed_repairs'])
        tiny = b.init_batch('tiny-attempts', self.root / 'batches', self.approved, batch_size=1)
        tiny_dir = self.root / 'batches/tiny-attempts'
        b.record_pin(tiny_dir, tiny['pins'][0]['pin_id'], {'creative_plan': fixture_plan(tiny['pins'][0])}, self.approved)
        for _ in range(2):
            b.record_image_attempt(tiny_dir, tiny['pins'][0]['pin_id'])
        with self.assertRaisesRegex(b.BatchError, 'budget exhausted'):
            b.record_image_attempt(tiny_dir, tiny['pins'][0]['pin_id'])


if __name__ == '__main__':
    unittest.main()
