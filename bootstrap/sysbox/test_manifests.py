from pathlib import Path
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[2]


class SysboxTests(unittest.TestCase):
    def test_runtime_only_schedules_on_the_manually_configured_worker(self):
        runtime = yaml.safe_load((ROOT / "bootstrap/sysbox/runtimeclass.yml").read_text())
        self.assertEqual(runtime["handler"], "sysbox-runc")
        self.assertEqual(runtime["scheduling"]["nodeSelector"], {"kubernetes.io/hostname": "pmhoci2"})

    def test_docker_workloads_are_nonprivileged_and_user_namespaced(self):
        for file in ["solver/deployment.yml", "bootstrap/sysbox/smoke-job.yml"]:
            with self.subTest(file=file):
                spec = yaml.safe_load((ROOT / file).read_text())["spec"]["template"]["spec"]
                self.assertFalse(spec["hostUsers"])
                self.assertEqual(spec["runtimeClassName"], "sysbox-runc")
                self.assertFalse(spec.get("hostPID", False))
                self.assertFalse(spec.get("hostNetwork", False))
                for container in spec["containers"] + spec.get("initContainers", []):
                    self.assertFalse(container.get("securityContext", {}).get("privileged", False))
                for volume in spec.get("volumes", []):
                    self.assertNotIn("hostPath", volume)

    def test_solver_daemon_has_no_tcp_listener_and_preserves_app_storage(self):
        pod = yaml.safe_load((ROOT / "solver/deployment.yml").read_text())["spec"]["template"]["spec"]
        daemon = next(c for c in pod["containers"] if c["name"] == "dind")
        self.assertEqual(daemon["command"], ["dockerd"])
        self.assertEqual(daemon["args"], ["--host=unix:///var/run/docker.sock"])
        self.assertEqual(next(v for v in pod["volumes"] if v["name"] == "solver-pvc")["persistentVolumeClaim"]["claimName"], "solver-pvc")


if __name__ == "__main__":
    unittest.main()
