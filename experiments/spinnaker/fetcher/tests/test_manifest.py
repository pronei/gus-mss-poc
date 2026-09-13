import json, os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import registry

F = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fixtures')


def fixture(name):
    with open(os.path.join(F, name)) as f:
        return json.load(f)


class Shapes(unittest.TestCase):
    """The three manifest shapes the corpus actually contains, as recorded."""

    def test_oci_index_skips_attestation_children(self):
        idx = fixture('manifest_oci_index_clouddriver_5.95.0.json')
        self.assertEqual(idx['mediaType'], 'application/vnd.oci.image.index.v1+json')
        platforms = [(m['platform']['os'], m['platform']['architecture']) for m in idx['manifests']]
        self.assertIn(('unknown', 'unknown'), platforms)
        child = registry.select_platform(idx)
        self.assertEqual(child['platform']['architecture'], 'amd64')
        self.assertEqual(child['platform']['os'], 'linux')

    def test_docker_manifest_list(self):
        idx = fixture('manifest_list_orca_8.31.0.json')
        self.assertEqual(idx['mediaType'],
                         'application/vnd.docker.distribution.manifest.list.v2+json')
        self.assertEqual(registry.select_platform(idx)['digest'],
                         'sha256:8e6f2a13637a8d7edd3dd21e8f452bcab9d5c174d5c30b65a88248369f04aef1')

    def test_plain_v2_manifest_has_no_children(self):
        m = fixture('manifest_v2_gate_1.19.0-20201012200017.json')
        self.assertEqual(m['mediaType'], 'application/vnd.docker.distribution.manifest.v2+json')
        self.assertNotIn('manifests', m)
        self.assertTrue(m['layers'] and m['config']['digest'].startswith('sha256:'))

    def test_index_types_are_recognised(self):
        for name in ('manifest_oci_index_clouddriver_5.95.0.json', 'manifest_list_orca_8.31.0.json'):
            self.assertIn(fixture(name)['mediaType'], registry.INDEX_TYPES)
        self.assertIn(fixture('manifest_v2_gate_1.19.0-20201012200017.json')['mediaType'],
                      registry.MANIFEST_TYPES)

    def test_no_amd64_child_is_an_error(self):
        with self.assertRaises(registry.RegistryError):
            registry.select_platform({'manifests': [
                {'digest': 'sha256:x', 'platform': {'os': 'linux', 'architecture': 'arm64'}},
                {'digest': 'sha256:y', 'platform': {'os': 'unknown', 'architecture': 'unknown'}}]})


class Eras(unittest.TestCase):
    def test_registry_order_by_release(self):
        self.assertEqual(registry.registries_for((1, 38, 0))[0], registry.GAR)
        self.assertEqual(registry.registries_for((1, 28, 0))[0], registry.GAR)
        self.assertEqual(registry.registries_for((1, 23, 7))[0], registry.GCR)
        self.assertEqual(registry.registries_for((2026, 1, 0))[0], registry.GHCR)

    def test_every_era_keeps_the_others_as_fallback(self):
        for rel in ((1, 0, 0), (1, 30, 0), (2026, 3, 0)):
            self.assertEqual(sorted(registry.registries_for(rel)),
                             sorted([registry.GAR, registry.GCR, registry.GHCR]))


class Digests(unittest.TestCase):
    def test_recorded_manifests_hash_to_the_digests_in_boms_tsv(self):
        """Each fixture was saved as served; sha256 of the bytes is the content digest."""
        import hashlib
        want = {
            'manifest_oci_index_clouddriver_5.95.0.json':
                'sha256:4db25c293d928c32a7b60cfeb9bdbd408726b53f871e5b4b2da4bfa607e82e99',
            'manifest_list_orca_8.31.0.json':
                'sha256:7e90f1395efdc1f4e95136d4732395f88b01800ce59fa105d0182d60a7e54dc7',
            'manifest_v2_gate_1.19.0-20201012200017.json':
                'sha256:31fdb568e0b687dd45da245705cc9414aa51aa6d770b149ea3ce246842416635',
        }
        for name, digest in want.items():
            with open(os.path.join(F, name), 'rb') as f:
                self.assertEqual('sha256:' + hashlib.sha256(f.read()).hexdigest(), digest, name)


if __name__ == '__main__':
    unittest.main()
