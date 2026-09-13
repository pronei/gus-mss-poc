"""Opt-in checks that talk to the registries: GUS_NET_TESTS=1 python3 -m unittest ...

They are the acceptance items that cannot be recorded as fixtures: that every pin
of the range resolves anonymously, and that what the fetcher resolves equals what
S3 recorded independently weeks earlier.
"""
import csv, os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import bom, fetch, registry

RANGE = os.environ.get('GUS_NET_RANGE', '1.30.0..1.38.0')
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@unittest.skipUnless(os.environ.get('GUS_NET_TESTS') == '1', 'set GUS_NET_TESTS=1 to run')
class DryRun(unittest.TestCase):
    def test_every_pin_of_the_range_resolves_without_downloading(self):
        lo, hi = RANGE.split('..')
        releases, meta = bom.range_releases(lo, hi)
        self.assertFalse(meta['truncated'])
        self.assertTrue(releases)
        s3 = {}
        with open(os.path.join(ROOT, 'scout', 'S3', 'boms.tsv')) as f:
            for r in csv.DictReader(f, delimiter='\t'):
                if r['artifact_kind'] == 'container-image':
                    s3[(r['release'], r['service'])] = r['artifact_ref'].split('@')[-1]
        pins = checked = 0
        for rel in releases:
            bomv = bom.format_version(rel)
            parsed, _url, _sha = bom.fetch_bom(bomv)
            services = bom.pinned_services(parsed)
            self.assertEqual(len(services), 9, '%s pins %d services' % (bomv, len(services)))
            for svc, version in services:
                pins += 1
                d = fetch.dry_service(rel, svc, version)
                self.assertTrue(d['manifest_digest'].startswith('sha256:'))
                if (bomv, svc) in s3:
                    self.assertEqual(d['manifest_digest'], s3[(bomv, svc)], '%s %s' % (bomv, svc))
                    checked += 1
        print('\n   %d pins resolved, %d compared with boms.tsv' % (pins, checked))
        self.assertEqual(pins, len(releases) * 9)

    def test_ghcr_hands_an_anonymous_token(self):
        """The third era needs a token, but any caller can have one (S3 §2)."""
        tok = registry._bearer('ghcr.io', 'spinnaker', 'keel')
        self.assertTrue(tok and len(tok) > 20)


if __name__ == '__main__':
    unittest.main()
