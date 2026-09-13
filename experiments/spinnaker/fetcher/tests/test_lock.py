import hashlib, json, os, shutil, sys, tempfile, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import lock


def entry(jars):
    return {'version': '1.57.0', 'layer_digest': 'sha256:dead', 'classpath': ['config'] + sorted(jars),
            'start_script': {'path': 'bin/fiat', 'sha256': 'sha256:beef', 'size': 3},
            'jars': {n: {'sha256': 'sha256:' + hashlib.sha256(n.encode()).hexdigest(),
                         'size': len(n)} for n in jars},
            'jar_count': len(jars), 'fetched': '2026-09-12'}


class Determinism(unittest.TestCase):
    def test_same_content_different_insertion_order_is_byte_identical(self):
        a, b = lock.empty(), lock.empty()
        lock.put_bom(a, '1.38.0', {'timestamp': 't'})
        lock.put_entry(a, '1.38.0', 'gate', entry(['x.jar', 'a.jar']))
        lock.put_entry(a, '1.38.0', 'echo', entry(['b.jar']))
        lock.put_bom(b, '1.38.0', {'timestamp': 't'})
        lock.put_entry(b, '1.38.0', 'echo', entry(['b.jar']))
        lock.put_entry(b, '1.38.0', 'gate', entry(['a.jar', 'x.jar']))
        self.assertEqual(lock.dumps(a), lock.dumps(b))

    def test_classpath_order_is_preserved(self):
        d = lock.empty()
        lock.put_bom(d, '1.38.0', {})
        e = entry(['z.jar', 'a.jar'])
        e['classpath'] = ['config', 'z.jar', 'a.jar']
        lock.put_entry(d, '1.38.0', 'gate', e)
        back = json.loads(lock.dumps(d))
        self.assertEqual(back['boms']['1.38.0']['services']['gate']['classpath'],
                         ['config', 'z.jar', 'a.jar'])

    def test_save_load_round_trip_is_stable(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, 'corpus.lock')
            a = lock.empty()
            lock.put_bom(a, '1.30.0', {'timestamp': 't'})
            lock.put_entry(a, '1.30.0', 'orca', entry(['a.jar']))
            lock.save(p, a)
            first = open(p, 'rb').read()
            lock.save(p, lock.load(p))
            self.assertEqual(first, open(p, 'rb').read())

    def test_unknown_schema_is_refused(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, 'corpus.lock')
            with open(p, 'w') as f:
                json.dump({'schema': 'something-else'}, f)
            with self.assertRaises(RuntimeError):
                lock.load(p)


class Materialised(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.entry = entry(['a.jar', 'b.jar'])
        root = os.path.join(self.dir, '1.38.0', 'fiat')
        os.makedirs(os.path.join(root, 'bin'))
        os.makedirs(os.path.join(root, 'lib'))
        with open(os.path.join(root, 'bin', 'fiat'), 'wb') as f:
            f.write(b'abc')
        for n in ('a.jar', 'b.jar'):
            with open(os.path.join(root, 'lib', n), 'wb') as f:
                f.write(n.encode())
        self.root = root

    def tearDown(self):
        shutil.rmtree(self.dir)

    def test_present_tree_passes_quick_and_full(self):
        self.assertTrue(lock.materialised(self.dir, '1.38.0', 'fiat', self.entry))
        self.assertTrue(lock.materialised(self.dir, '1.38.0', 'fiat', self.entry, full=True))

    def test_missing_jar_fails(self):
        os.remove(os.path.join(self.root, 'lib', 'a.jar'))
        self.assertFalse(lock.materialised(self.dir, '1.38.0', 'fiat', self.entry))

    def test_truncated_jar_fails_on_size(self):
        with open(os.path.join(self.root, 'lib', 'a.jar'), 'wb') as f:
            f.write(b'')
        self.assertFalse(lock.materialised(self.dir, '1.38.0', 'fiat', self.entry))

    def test_corrupted_jar_of_the_right_size_fails_only_on_full(self):
        p = os.path.join(self.root, 'lib', 'a.jar')
        with open(p, 'wb') as f:
            f.write(b'X' * len('a.jar'))
        self.assertTrue(lock.materialised(self.dir, '1.38.0', 'fiat', self.entry))
        self.assertFalse(lock.materialised(self.dir, '1.38.0', 'fiat', self.entry, full=True))

    def test_missing_start_script_fails(self):
        os.remove(os.path.join(self.root, 'bin', 'fiat'))
        self.assertFalse(lock.materialised(self.dir, '1.38.0', 'fiat', self.entry))


if __name__ == '__main__':
    unittest.main()
