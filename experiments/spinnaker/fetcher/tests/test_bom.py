import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import bom

F = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fixtures')


def fixture(name):
    with open(os.path.join(F, name)) as f:
        return f.read()


class ParseBom(unittest.TestCase):
    def test_plain_bom(self):
        b = bom.parse_bom(fixture('bom_1.38.0.yml'))
        self.assertEqual(b['version'], '1.38.0')
        self.assertEqual(b['timestamp'], '2025-04-18 20:25:26')
        pins = dict(bom.pinned_services(b))
        self.assertEqual(len(pins), 9)
        self.assertEqual(pins['gate'], '6.69.0')
        self.assertEqual(pins['clouddriver'], '5.95.0')
        self.assertEqual(pins['kayenta'], '2.46.0')

    def test_quoted_keys(self):
        """52 BOMs in the 1.19.12-1.26.7 band quote every key."""
        b = bom.parse_bom(fixture('bom_1.23.7.yml'))
        self.assertEqual(b['version'], '1.23.7')
        self.assertEqual(b['timestamp'], '2021-02-18 21:17:48')
        pins = dict(bom.pinned_services(b))
        self.assertEqual(len(pins), 9)
        self.assertEqual(pins['gate'], '1.19.0-20201012200017')

    def test_non_services_are_ignored(self):
        for name in ('bom_1.38.0.yml', 'bom_1.23.7.yml'):
            b = bom.parse_bom(fixture(name))
            pinned = dict(bom.pinned_services(b))
            for k in bom.IGNORED:
                self.assertNotIn(k, pinned, '%s leaked from %s' % (k, name))
            # deck and the monitoring daemons are in the file but never in scope
            self.assertIn('deck', b['services'])

    def test_keel_is_never_pinned(self):
        for name in ('bom_1.38.0.yml', 'bom_1.23.7.yml'):
            self.assertNotIn('keel', bom.parse_bom(fixture(name))['services'])

    def test_commit_is_kept(self):
        b = bom.parse_bom(fixture('bom_1.38.0.yml'))
        self.assertRegex(b['services']['gate']['commit'], r'^[0-9a-f]{6,}$')

    def test_docker_registry_field_is_read_but_not_trusted(self):
        """1.23.7's images live on GCR although the BOM names GAR (S3 §2)."""
        b = bom.parse_bom(fixture('bom_1.23.7.yml'))
        self.assertEqual(b['docker_registry'], 'us-docker.pkg.dev/spinnaker-community/docker')


class Versions(unittest.TestCase):
    def test_round_trip_and_order(self):
        self.assertEqual(bom.parse_version('1.38.0'), (1, 38, 0))
        self.assertEqual(bom.format_version((1, 38, 0)), '1.38.0')
        self.assertLess(bom.parse_version('1.9.0'), bom.parse_version('1.30.0'))
        self.assertLess(bom.parse_version('1.38.0'), bom.parse_version('2025.0.0'))

    def test_rejects_non_releases(self):
        for bad in ('master-20240101000000', '1.38', '1.38.0-rc1', 'latest'):
            with self.assertRaises(ValueError):
                bom.parse_version(bad)

    def test_release_key_filter(self):
        keys = ['bom/1.38.0.yml', 'bom/master-20240101000000.yml', 'bom/io-codelab.yml',
                'bom/2025.0.0.yml', 'bom/1.24.0.yml.bak']
        got = [m.group(1) for k in keys if (m := bom.RELEASE_KEY.match(k))]
        self.assertEqual(got, ['1.38.0', '2025.0.0'])


if __name__ == '__main__':
    unittest.main()
