import subprocess
import unittest
from unittest.mock import Mock

import yaml

from provision import ROOT
from welplan import EXTERNAL, complete_credentials
from welplan_dns import HOST, LEGACY, TARGETS, retarget


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

    def test_dns_cutover_updates_only_exact_legacy_address_and_is_idempotent(self):
        client = Mock()
        values = {LEGACY}
        def post(path, data):
            self.assertEqual(data['domain'], HOST)
            if path == 'zones/records/get':
                return {'response': {'records': [{'name':HOST,'type':'A','rData':{'ipAddress':v}} for v in values]}}
            if path == 'zones/records/update':
                self.assertEqual(data['ipAddress'], LEGACY)
                values.remove(LEGACY);values.add(data['newIpAddress'])
            elif path == 'zones/records/add':
                self.assertEqual(data['overwrite'], 'false');values.add(data['ipAddress'])
            else:self.fail('Unexpected DNS operation')
            return {'status':'ok'}
        client.post.side_effect = post
        retarget(client)
        self.assertEqual(values, TARGETS)
        client.post.reset_mock();retarget(client)
        self.assertTrue(all(c.args[0]=='zones/records/get' for c in client.post.call_args_list))

    def test_dns_cutover_refuses_unrecognized_or_concurrently_changed_records(self):
        for records in [[{'name':HOST,'type':'A','rData':{'ipAddress':'192.0.2.99'}}], [{'name':HOST,'type':'AAAA','rData':{'ipAddress':'2001:db8::1'}}]]:
            client=Mock();client.post.return_value={'response':{'records':records}}
            with self.assertRaises(RuntimeError):retarget(client)
            self.assertTrue(all(c.args[0]=='zones/records/get' for c in client.post.call_args_list))


if __name__ == '__main__':
    unittest.main()
