"""Revalidate live assets and affiliate redirects, then create a freshly timed CSV."""
import argparse
import json
from pathlib import Path
import re
import sys

import pinterest_batch as batch
import pinterest_services as services


def prepare_export(batch_dir, approved_path=batch.DEFAULT_APPROVED):
    batch_dir = Path(batch_dir)
    def verify_pins(manifest, directory):
        links = {}
        for pin in manifest['pins']:
            batch.check_approval(manifest, approved_path)
            pin.pop('media_verified_at', None)
            pin.pop('link_verified_at', None)
            failures = []
            try:
                media = services.verify_media(pin['media_url'], local=directory / pin['image_path'])
                pin['media_verified_at'] = media['media_verified_at']
            except (ValueError, OSError):
                failures.append('media verification failed')
                pin.pop('media_verified_at', None)
            if failures:
                pin['verification_failure'] = '; '.join(failures)
                continue
            pair = (pin['short_url'], pin['affiliate_url'])
            try:
                if pair not in links:
                    links[pair] = services.verify_link(*pair)
                pin['link_verified_at'] = links[pair]['link_verified_at']
            except (ValueError, OSError):
                failures.append('link verification failed')
                pin.pop('link_verified_at', None)
            if failures:
                pin['verification_failure'] = '; '.join(failures)
            else:
                pin.pop('verification_failure', None)
    return batch.export_batch(batch_dir, approved_path, verify_pins=verify_pins)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--batch', required=True)
    parser.add_argument('--batches-root', default=str(Path(__file__).with_name('batches')))
    parser.add_argument('--approved-file', default=str(batch.DEFAULT_APPROVED))
    args = parser.parse_args(argv)
    try:
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,79}', args.batch):
            raise batch.BatchError('Invalid batch ID')
        result = prepare_export(Path(args.batches_root) / args.batch, args.approved_file)
        print(json.dumps(result))
        return 0
    except (ValueError, OSError, KeyError) as exc:
        message = str(exc) if isinstance(exc, (batch.BatchError, services.ServiceError)) else 'Export failed; check batch files and permissions'
        print(json.dumps({'error': message}), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
