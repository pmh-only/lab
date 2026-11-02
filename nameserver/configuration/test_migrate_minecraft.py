import copy
import json
from pathlib import Path
import unittest
from unittest.mock import Mock

from migrate_minecraft import migrate
from records import FIELDS


class MinecraftMigrationTests(unittest.TestCase):
    def setUp(self):
        self.desired = json.loads(Path(__file__).with_name("imported-records.json").read_text())
        self.state = [
            {"name": "mc.pmh.codes", "type": "A", "rData": {"ipAddress": "168.107.9.91"}},
            {"name": "_minecraft._tcp.pmh.codes", "type": "SRV", "rData": {
                "priority": 0, "weight": 5, "port": 25565, "target": "mc.pmh.codes"}},
        ]
        self.client = Mock()
        self.client.post.side_effect = self.post

    def post(self, path, payload):
        if path == "zones/records/get":
            return {"response": {"records": copy.deepcopy([
                r for r in self.state if r["name"] == payload["domain"]])}}
        if path == "zones/records/add":
            self.state.append({"name": payload["domain"], "type": payload["type"],
                               "rData": {k: payload[k] for k in FIELDS[payload["type"]]}})
        elif path == "zones/records/update":
            record = next(r for r in self.state if r["name"] == payload["domain"] and r["type"] == payload["type"])
            for key in FIELDS[payload["type"]]:
                self.assertEqual(record["rData"][key], payload[key])
                record["rData"][key] = payload["new" + key[0].upper() + key[1:]]
        else:
            self.fail(f"Unexpected mutation: {path}")
        return {"status": "ok"}

    def test_migration_preserves_game_endpoint_and_is_idempotent(self):
        migrate(self.client, self.desired)
        writes = [c.args for c in self.client.post.call_args_list if c.args[0] != "zones/records/get"]
        self.assertEqual(writes[0][1]["domain"], "play.pmh.codes")
        updates = [p for path, p in writes if path == "zones/records/update"]
        self.assertEqual([p["type"] for p in updates], ["SRV", "A"])
        self.assertIn({"name": "play.pmh.codes", "type": "A", "rData": {"ipAddress": "168.107.9.91"}}, self.state)
        self.client.reset_mock()
        migrate(self.client, self.desired)
        self.assertTrue(all(c.args[0] == "zones/records/get" for c in self.client.post.call_args_list))

    def test_unexpected_existing_data_prevents_all_writes(self):
        self.state[1]["rData"]["target"] = "unexpected.example"
        with self.assertRaises(RuntimeError):
            migrate(self.client, self.desired)
        self.assertTrue(all(c.args[0] == "zones/records/get" for c in self.client.post.call_args_list))


if __name__ == "__main__":
    unittest.main()
