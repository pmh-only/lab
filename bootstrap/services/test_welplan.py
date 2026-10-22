import subprocess
import unittest

import yaml

from provision import ROOT
from welplan import EXTERNAL, complete_credentials


class WelplanTests(unittest.TestCase):
    def test_external_inputs_are_preserved_and_only_native_internal_keys_created(self):
        data = {k: 'external-fixture-' + k for k in EXTERNAL}
        data['SLACK_CLIENT_ID'] = '12345.67890'
        result = complete_credentials(data)
        for k in EXTERNAL:
            self.assertEqual(result[k], data[k])
        self.assertEqual(set(result) - set(data), {'PGPASSWORD', 'INDEXNOW_KEY', 'REVIEW_JWT_SECRET'})
        self.assertEqual(complete_credentials(result), result)
        self.assertGreaterEqual(len(result['PGPASSWORD']), 48)
        with self.assertRaises(RuntimeError):
            complete_credentials({**data, 'SLACK_CLIENT_ID': 'A01234567'})

    def test_native_schema_hook_avoids_fresh_database_web_worker_creation_race(self):
        docs = list(yaml.safe_load_all(subprocess.check_output(['kubectl', 'kustomize', str(ROOT / 'welplan')], text=True)))
        job = next(d for d in docs if d['kind'] == 'Job')
        self.assertEqual(job['metadata']['annotations']['argocd.argoproj.io/sync-wave'], '-1')
        container = job['spec']['template']['spec']['containers'][0]
        self.assertIn('ensureDbInitialized', str(container['command']))
        self.assertNotIn('createService', str(container['command']))
        self.assertNotIn('WELSTORY_PASSWORD', str(container['env']))
        self.assertIn('@sha256:', container['image'])
        deployment = next(d for d in docs if d['kind'] == 'Deployment')
        self.assertEqual(deployment['spec']['strategy']['type'], 'Recreate')
        pod = deployment['spec']['template']['spec']
        self.assertFalse(pod['automountServiceAccountToken'])
        env = {e['name']: e for e in pod['containers'][0]['env']}
        self.assertEqual(env['SLACK_CLIENT_ID']['valueFrom']['secretKeyRef']['key'], 'SLACK_CLIENT_ID')
        self.assertEqual(env['ADMIN_OIDC_CLIENT_SECRET']['valueFrom']['secretKeyRef']['name'], 'welplan-admin-oidc')
        self.assertEqual(env['WELPLAN_VERBOSE_LOGS']['value'], '0')
        self.assertEqual(env['SLACK_OAUTH_REDIRECT_URI']['value'], 'https://welplan.pmh.codes/webhooks/slack/callback')

    def test_original_session_gate_protects_destructive_api_and_startup_preserves_settings(self):
        code = (ROOT / 'welplan/prepare-safety.mjs').read_text()
        self.assertIn('4a1b57d086ccbdbe599c2202cbae5ec3f2c36fd675770798e285127208004f27', code)
        self.assertIn('pathname === "/api/cache/clear" || pathname === "/admin"', code)
        self.assertIn('Subscription preferences retained.', code)
        self.assertIn('Legacy selection data retained.', code)
        self.assertIn('Legacy review metadata retained.', code)
        self.assertIn('source.split(before).length !== 2', code)
        docs = list(yaml.safe_load_all(subprocess.check_output(['kubectl', 'kustomize', str(ROOT / 'welplan')], text=True)))
        for doc in docs:
            if doc['kind'] not in {'Deployment', 'Job'}:
                continue
            pod = doc['spec']['template']['spec']
            self.assertEqual(pod['securityContext']['runAsUser'], 1000)
            self.assertEqual(pod['initContainers'][0]['name'], 'prepare-native-safety')
            mounts = pod['containers'][0]['volumeMounts']
            self.assertIn('/app/worker/dist/webapp/src/lib/server/db/index.js', [m['mountPath'] for m in mounts])


if __name__ == '__main__':
    unittest.main()
