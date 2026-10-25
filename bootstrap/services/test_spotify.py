import base64
import io
import json
import unittest
import subprocess
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

    def test_mongo_authentication_keeps_persistent_volume_and_legacy_sidecars_disabled(self):
        deployment = yaml.safe_load((ROOT / 'database/mongo/deployment.yml').read_text())
        pod = deployment['spec']['template']['spec']
        container = pod['containers'][0]
        self.assertIn('--auth', container['args'])
        self.assertIn('--bind_ip_all', container['args'])
        self.assertEqual(pod['volumes'][0]['persistentVolumeClaim']['claimName'], 'mongo-pvc')
        kustomization = yaml.safe_load((ROOT / 'database/kustomization.yml').read_text())
        self.assertTrue(any('/spec/template/spec/initContainers' in p['patch'] for p in kustomization['patches']))
        self.assertIn('./backup/mongo', kustomization['resources'])

    def test_spotify_native_workloads_use_real_secret_identity_and_scoped_database(self):
        docs = list(yaml.safe_load_all(subprocess.check_output(['kubectl', 'kustomize', str(ROOT / 'spotify')], text=True)))
        deployments = {d['metadata']['name']: d for d in docs if d['kind'] == 'Deployment'}
        self.assertEqual(set(deployments), {'spotify-api', 'spotify-web', 'spotify-stats-worker'})
        for deployment in deployments.values():
            self.assertEqual(deployment['spec']['strategy']['type'], 'Recreate')
            self.assertFalse(deployment['spec']['template']['spec']['automountServiceAccountToken'])
        for name in ['spotify-api', 'spotify-web']:
            container = deployments[name]['spec']['template']['spec']['containers'][0]
            env = {e['name']: e for e in container['env']}
            self.assertEqual(env['SPOTIFY_PUBLIC']['valueFrom']['secretKeyRef']['key'], 'SPOTIFY_PUBLIC')
            self.assertEqual(env['SPOTIFY_SECRET']['valueFrom']['secretKeyRef']['key'], 'SPOTIFY_SECRET')
            self.assertIn('@sha256:', container['image'])
        api = deployments['spotify-api']['spec']['template']['spec']['containers'][0]
        env = {e['name']: e for e in api['env']}
        self.assertEqual(env['MONGO_NO_ADMIN_RIGHTS']['value'], 'true')
        self.assertEqual(env['LOG_LEVEL']['value'], 'warn')
        self.assertNotIn('OFFLINE_DEV_ID', env)
        pvc = next(d for d in docs if d['kind'] == 'PersistentVolumeClaim')
        self.assertEqual(pvc['metadata']['annotations']['argocd.argoproj.io/sync-options'], 'Prune=false')

    def test_playlist_compatibility_changes_one_verified_native_endpoint_not_functionality(self):
        source = (ROOT / 'spotify/prepare-api.mjs').read_text()
        self.assertIn('79c58a52a835b5b228a5e3ceaeb44b22ae767c3f85ba1f3d596f2818ac6b37af', source)
        self.assertIn("const previous = '/playlists/${id}/tracks'", source)
        self.assertIn("const replacement = '/playlists/${id}/items'", source)
        self.assertIn('source.split(previous).length !== 2', source)
        self.assertIn('source.replace(previous, replacement)', source)
        self.assertIn('user-read-currently-playing', source)
        self.assertIn('source.split(scopeAnchor).length !== 2', source)
        self.assertIn('source.split(proxyAnchor).length !== 2', source)
        self.assertIn('app.set("trust proxy", 1)', source)
        route = yaml.safe_load((ROOT / 'spotify/ingress.yml').read_text())
        headers = route['spec']['rules'][0]['filters'][0]['requestHeaderModifier']['set']
        self.assertIn({'name': 'X-Forwarded-Proto', 'value': 'https'}, headers)
        self.assertIn({'name': 'X-Forwarded-Host', 'value': 'spotify.pmh.codes'}, headers)


if __name__ == '__main__':
    unittest.main()
