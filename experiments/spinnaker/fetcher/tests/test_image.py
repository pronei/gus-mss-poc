import json, os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import image

F = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fixtures')


def fixture(name, binary=False):
    with open(os.path.join(F, name), 'rb' if binary else 'r') as f:
        return f.read() if binary else json.load(f)


class LayerOrder(unittest.TestCase):
    def setUp(self):
        self.manifest = fixture('manifest_oci_image_clouddriver_5.95.0.json')
        self.config = fixture('config_clouddriver_5.95.0.json')

    def test_config_history_names_the_copy_layer(self):
        order, meta = image.layer_order(self.manifest, self.config, 'clouddriver')
        self.assertEqual(order[0], 11)                 # COPY .../install/clouddriver /opt/clouddriver
        self.assertIn(11, meta['hinted'])
        self.assertEqual(len(order), len(self.manifest['layers']))
        self.assertEqual(sorted(order), list(range(len(self.manifest['layers']))))

    def test_size_fallback_without_a_config(self):
        order, meta = image.layer_order(self.manifest, {}, 'clouddriver')
        sizes = [self.manifest['layers'][i].get('size', 0) for i in order]
        self.assertEqual(sizes, sorted(sizes, reverse=True))
        self.assertEqual(order[0], 11)                 # the app layer is also the largest here

    def test_hint_wins_over_size(self):
        manifest = {'layers': [{'digest': 'sha256:a', 'size': 900},
                               {'digest': 'sha256:b', 'size': 10}]}
        config = {'history': [{'created_by': 'RUN apk add everything'},
                              {'created_by': 'COPY gate-web/build/install/gate /opt/gate # buildkit'}]}
        order, meta = image.layer_order(manifest, config, 'gate')
        self.assertEqual(order, [1, 0])
        self.assertEqual(meta['hinted'], [1])

    def test_empty_layers_do_not_shift_the_mapping(self):
        manifest = {'layers': [{'digest': 'sha256:a', 'size': 1}, {'digest': 'sha256:b', 'size': 2}]}
        config = {'history': [{'created_by': 'ADD rootfs'},
                              {'created_by': 'ENV FOO=bar', 'empty_layer': True},
                              {'created_by': 'COPY x /opt/echo # buildkit'}]}
        order, _ = image.layer_order(manifest, config, 'echo')
        self.assertEqual(order[0], 1)


class Classpath(unittest.TestCase):
    def test_real_start_script(self):
        cp, raw = image.parse_classpath(fixture('start_script_fiat_1.57.0.sh', binary=True))
        self.assertEqual(cp[0], 'config')
        self.assertEqual(cp[1], 'fiat-web-1.57.0.jar')
        self.assertEqual(len(cp), 291)
        self.assertTrue(raw.startswith('$APP_HOME/config:'))
        self.assertTrue(all(e.endswith('.jar') for e in cp[1:]))

    def test_cygpath_rewrite_is_not_the_classpath(self):
        script = b'\n'.join([b'#!/bin/sh',
                             b'CLASSPATH=$APP_HOME/config:$APP_HOME/lib/gate-web.jar',
                             b'    CLASSPATH=$( cygpath --path --mixed "$CLASSPATH" )'])
        cp, raw = image.parse_classpath(script)
        self.assertEqual(cp, ['config', 'gate-web.jar'])

    def test_continued_line(self):
        script = b'CLASSPATH=$APP_HOME/config:\\\n$APP_HOME/lib/a.jar:$APP_HOME/lib/b.jar\n'
        cp, _ = image.parse_classpath(script)
        self.assertEqual(cp, ['config', 'a.jar', 'b.jar'])

    def test_no_classpath_line(self):
        self.assertEqual(image.parse_classpath(b'#!/bin/sh\necho hi\n'), ([], None))

    def test_unversioned_gcr_era_names(self):
        """Run A names the service's own jars without a version; order still holds."""
        script = b'CLASSPATH=$APP_HOME/config:$APP_HOME/lib/gate-web.jar:$APP_HOME/lib/kork-core-7.78.0.jar\n'
        cp, _ = image.parse_classpath(script)
        self.assertEqual(cp, ['config', 'gate-web.jar', 'kork-core-7.78.0.jar'])


class Names(unittest.TestCase):
    def test_norm(self):
        self.assertEqual(image._norm('./opt/gate/lib/a.jar'), 'opt/gate/lib/a.jar')
        self.assertEqual(image._norm('/opt/gate/lib/a.jar'), 'opt/gate/lib/a.jar')
        self.assertEqual(image._norm('opt/gate/lib/a.jar'), 'opt/gate/lib/a.jar')


if __name__ == '__main__':
    unittest.main()
