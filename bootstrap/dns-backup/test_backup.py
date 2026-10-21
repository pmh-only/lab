import hashlib
import io
from pathlib import Path
import tarfile
import tempfile
import unittest

from backup import operator_token, validate_dns_archive, validate_snapshot, write_private


def archive(files):
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w:gz") as target:
        for name, data in files.items():
            metadata = tarfile.TarInfo(name)
            metadata.size = len(data)
            target.addfile(metadata, io.BytesIO(data))
    return output.getvalue()


class BackupTests(unittest.TestCase):
    def test_dns_configuration_and_all_zones_are_required(self):
        files = {"./dns.config": b"configuration", "./auth.config": b"credentials", "./webservice.config": b"settings", "./zones/example.test.zone": b"fresh-zone-data"}
        self.assertEqual(validate_dns_archive(archive(files), ["example.test"]), 4)
        with self.assertRaises(RuntimeError):
            validate_dns_archive(archive(files), ["missing.test"])

    def test_unsafe_and_volatile_members_are_rejected(self):
        required = {"dns.config": b"configuration", "auth.config": b"credentials", "webservice.config": b"settings"}
        for path in ["../escape", "/absolute", "./stats/queries", "./logs/requests", "./cache.bin"]:
            with self.subTest(path=path), self.assertRaises(RuntimeError):
                validate_dns_archive(archive({**required, path: b"data"}), [])

    def test_root_or_non_userpass_credentials_are_rejected(self):
        for identity in [
            {"id": "root-placeholder", "policies": ["root"], "path": "auth/token/root"},
            {"id": "root-placeholder", "identity_policies": ["root"], "path": "auth/userpass/login/owner"},
            {"id": "app-placeholder", "policies": ["lab-cert-manager"], "path": "auth/kubernetes/login"},
        ]:
            with self.subTest(path=identity["path"]), self.assertRaises(RuntimeError):
                operator_token(identity)
        self.assertEqual(operator_token({"id": "operator-placeholder", "policies": ["full-admin"], "path": "auth/userpass/login/owner"}), "operator-placeholder")

    def test_snapshot_checksums_are_verified(self):
        files = {"meta.json": b'{"Version":1}', "state.bin": b"encrypted-state-placeholder"}
        checksums = "".join(hashlib.sha256(data).hexdigest() + "  " + name + "\n" for name, data in files.items()).encode()
        valid = {**files, "SHA256SUMS": checksums, "SHA256SUMS.sealed": b"sealed-checksum-placeholder"}
        validate_snapshot(archive(valid))
        with self.assertRaises(RuntimeError):
            validate_snapshot(archive({**valid, "state.bin": b"modified"}))

    def test_missing_sealed_snapshot_state_is_rejected(self):
        with self.assertRaises(RuntimeError):
            validate_snapshot(archive({"state.bin": b"state"}))

    def test_private_files_are_not_overwritten(self):
        with tempfile.TemporaryDirectory(dir="/tmp/opencode") as temporary:
            path = Path(temporary) / "backup"
            write_private(path, b"encrypted-data-placeholder")
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            with self.assertRaises(FileExistsError):
                write_private(path, b"replacement")
            self.assertEqual(path.read_bytes(), b"encrypted-data-placeholder")


if __name__ == "__main__":
    unittest.main()
