import base64
import io
import json
import unittest
from unittest.mock import patch

import yaml

from mongo import ensure_users, spotify_identity
from provision import ROOT
from spotify import verify_spotify


class SpotifyTests(unittest.TestCase):
    def test_mongo_identity_has_only_the_declared_database_and_auth_source(self):
        uri = 'mongodb://spotify:' + 'x' * 64 + '@mongo-service.database.svc.cluster.local:27017/your_spotify?authSource=your_spotify'
        self.assertEqual(spotify_identity(uri)['database'], 'your_spotify')
        for bad in [uri.replace('authSource=your_spotify', 'authSource=admin'), uri.replace('/your_spotify?', '/other?'), uri.replace('spotify:', 'root:')]:
            with self.assertRaises(RuntimeError):
                spotify_identity(bad)

    def test_native_mongo_user_creation_is_labeled_guarded_and_never_resets_users(self):
        uri = 'mongodb://spotify:' + 'x' * 64 + '@mongo-service.database.svc.cluster.local:27017/your_spotify?authSource=your_spotify'
        with patch('mongo.shell') as run:
            ensure_users({'username': 'lab-admin', 'password': 'y' * 64}, uri)
        code = run.call_args.args[0]
        self.assertIn("users.users.length !== 0", code)
        self.assertIn("Existing application data requires review", code)
        self.assertIn("managedBy:'lab-spotify-v1'", code)
        self.assertIn("role:'readWrite', db:input.app.database", code)
        self.assertNotIn('updateUser', code)
        self.assertNotIn('dropDatabase', code)

    def test_real_spotify_secret_is_only_http_header_not_url_and_token_not_returned(self):
        credentials = {'SPOTIFY_PUBLIC': 'test-client', 'SPOTIFY_SECRET': 'private-test-secret'}
        with patch('spotify.urllib.request.urlopen', return_value=io.BytesIO(json.dumps({'access_token': 'private-token', 'token_type': 'Bearer'}).encode())) as call:
            self.assertIsNone(verify_spotify(credentials))
        request = call.call_args.args[0]
        self.assertNotIn('private-test-secret', request.full_url)
        expected = base64.b64encode(b'test-client:private-test-secret').decode()
        self.assertEqual(request.get_header('Authorization'), 'Basic ' + expected)

    def test_mongo_authentication_keeps_persistent_volume_and_backup_deferral(self):
        deployment = yaml.safe_load((ROOT / 'database/mongo/deployment.yml').read_text())
        pod = deployment['spec']['template']['spec']
        container = pod['containers'][0]
        self.assertIn('--auth', container['args'])
        self.assertIn('--bind_ip_all', container['args'])
        self.assertEqual(pod['volumes'][0]['persistentVolumeClaim']['claimName'], 'mongo-pvc')
        kustomization = yaml.safe_load((ROOT / 'database/kustomization.yml').read_text())
        self.assertIn('backpack', str(kustomization['patches']))


if __name__ == '__main__':
    unittest.main()
