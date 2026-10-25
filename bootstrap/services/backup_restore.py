#!/usr/bin/env python3
"""Restore completed remote database backups only into throwaway, isolated Pods.

No production database credentials, Services, PVCs, hostPaths, or API tokens are
mounted. NetworkPolicy denies access to live databases. Removes only the unique
namespace this invocation created, including its ephemeral plaintext dumps.
"""

import argparse
import base64
import importlib.util
import json
import re
import secrets
import subprocess
import sys

from minio import Minio
import yaml

from provision import ROOT


RESTORE = {
    "clickhouse": r"""
set -eu
umask 077
mkdir -p /work/data /work/access
cat > /work/config.xml <<'XML'
<clickhouse>
  <logger><level>warning</level><log>/work/server.log</log><errorlog>/work/error.log</errorlog></logger>
  <listen_host>127.0.0.1</listen_host><tcp_port>9001</tcp_port>
  <path>/work/data/</path><tmp_path>/tmp/clickhouse/</tmp_path>
  <user_directories><users_xml><path>/work/users.xml</path></users_xml><local_directory><path>/work/access/</path></local_directory></user_directories>
</clickhouse>
XML
cat > /work/users.xml <<'XML'
<clickhouse>
  <profiles><default><max_memory_usage>2000000000</max_memory_usage></default></profiles>
  <users><default><password></password><networks><ip>127.0.0.1</ip></networks><profile>default</profile><quota>default</quota><access_management>1</access_management></default></users>
  <quotas><default><interval><duration>3600</duration><queries>0</queries><errors>0</errors><result_rows>0</result_rows><read_rows>0</read_rows><execution_time>0</execution_time></interval></default></quotas>
</clickhouse>
XML
clickhouse-server --config-file=/work/config.xml > /work/start.log 2>&1 &
server=$!
for attempt in $(seq 1 120); do
  if clickhouse-client --host=127.0.0.1 --port=9001 --query='SELECT 1' > /dev/null 2>&1; then break; fi
  kill -0 "$server"
  sleep 1
done
printf "RESTORE ALL FROM S3('http://pmhraspberry.tailscale.svc.cluster.local:9000/dbdump/%s', '%s', '%s')\n" "${BACKUP_PREFIX%/}" "$AWS_ACCESS_KEY_ID" "$AWS_SECRET_ACCESS_KEY" > /work/request.sql
clickhouse-client --host=127.0.0.1 --port=9001 --multiquery < /work/request.sql > /work/restore.log 2>&1
tables="$(clickhouse-client --host=127.0.0.1 --port=9001 --query="SELECT count() FROM system.tables WHERE database NOT IN ('system','INFORMATION_SCHEMA','information_schema')")"
kill -TERM "$server"
wait "$server"
printf 'RESTORE_OK clickhouse tables=%s\n' "$tables"
""",
    "pgsql": r"""
set -eu
umask 077
cd /backup
initdb -D /work/data -U restore_admin -A trust > /work/init.log 2>&1
pg_ctl -D /work/data -l /work/server.log -o '-h 127.0.0.1 -k /tmp' -w start > /work/start.log 2>&1
export PGHOST=127.0.0.1 PGUSER=restore_admin
psql -X -d postgres -v ON_ERROR_STOP=1 -f globals.sql > /work/globals.log 2>&1
while IFS= read -r database; do
  case "$database" in ''|*[!a-zA-Z0-9_-]*) exit 1;; esac
  if [ "$database" = postgres ]; then
    pg_restore --exit-on-error -d postgres "$database.dump" > /work/restore.log 2>&1
  else
    pg_restore --exit-on-error --create -d postgres "$database.dump" > /work/restore.log 2>&1
  fi
  psql -X -d "$database" -v ON_ERROR_STOP=1 -At -c 'SELECT count(*) FROM pg_class WHERE relkind IN ('"'"'r'"'"','"'"'p'"'"') AND relnamespace NOT IN (SELECT oid FROM pg_namespace WHERE nspname LIKE '"'"'pg_%'"'"' OR nspname='"'"'information_schema'"'"')' >> /work/table-counts
done < databases
pg_ctl -D /work/data -m fast -w stop > /work/stop.log 2>&1
printf 'RESTORE_OK pgsql databases=%s\n' "$(wc -l < databases)"
""",
    "mysql": r"""
set -eu
umask 077
mysqld --no-defaults --initialize-insecure --datadir=/work/data > /work/init.log 2>&1
mysqld --no-defaults --datadir=/work/data --socket=/tmp/mysql.sock --pid-file=/tmp/mysql.pid --bind-address=127.0.0.1 --mysql-native-password=ON --log-bin-trust-function-creators=ON --event-scheduler=OFF > /work/server.log 2>&1 &
server=$!
for attempt in $(seq 1 120); do
  if mysqladmin --no-defaults --socket=/tmp/mysql.sock -uroot ping --silent > /dev/null 2>&1; then break; fi
  kill -0 "$server"
  sleep 1
done
mysql --no-defaults --socket=/tmp/mysql.sock -uroot < /backup/all-databases.sql > /work/restore.log 2>&1
# Keep the established server running until import finishes; no live endpoint
# or source root password is available to this Pod. Shut down via its own PID.
kill -TERM "$server"
wait "$server"
echo 'RESTORE_OK mysql native SQL import completed'
""",
    "mongo": r"""
set -eu
umask 077
mkdir -p /work/data
mongod --dbpath=/work/data --bind_ip=127.0.0.1 --port=27017 --logpath=/work/server.log --fork > /work/start.log 2>&1
mongorestore --host=127.0.0.1 --port=27017 --archive=/backup/all-databases.archive.gz --gzip --stopOnError > /work/restore.log 2>&1
mongosh --quiet --host=127.0.0.1 --eval 'const r=db.getSiblingDB("admin").runCommand({listDatabases:1,nameOnly:true}); if(r.ok!==1)quit(1); print("RESTORE_OK mongo databases="+r.databases.length);' > /work/check.log 2>&1
grep '^RESTORE_OK' /work/check.log
mongod --dbpath=/work/data --shutdown > /work/stop.log 2>&1
""",
}
RESTORE["immich"] = RESTORE["pgsql"].replace("RESTORE_OK pgsql", "RESTORE_OK immich").replace(
    "-h 127.0.0.1 -k /tmp'", "-h 127.0.0.1 -k /tmp -c shared_preload_libraries=vchord.so,vectors.so'")


def kubectl(*args, payload=None, timeout=30):
    result = subprocess.run(["kubectl", *args], input=None if payload is None else json.dumps(payload),
                            text=True, capture_output=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError("Isolated restore Kubernetes operation failed; output suppressed")
    return result.stdout


def restore_pod(namespace, engine, prefix, native, uploader):
    prefix_engine = "pgsql-immich" if engine == "immich" else engine
    if engine not in RESTORE or not re.fullmatch(prefix_engine + r"/[a-zA-Z0-9T-]+/", prefix):
        raise RuntimeError("Unexpected backup prefix or database engine")
    security = {"allowPrivilegeEscalation": False, "readOnlyRootFilesystem": True, "capabilities": {"drop": ["ALL"]}}
    mounts = [{"name": n, "mountPath": p} for n, p in [("backup", "/backup"), ("work", "/work"), ("tmp", "/tmp")]]
    download = r"""
set -eu
umask 077
export AWS_EC2_METADATA_DISABLED=true
aws --endpoint-url "$S3_ENDPOINT_URL" s3 cp "s3://dbdump/$BACKUP_PREFIX" /backup/ --recursive --quiet
cd /backup
test -s _COMPLETE
test "$(sed -n 's/^sha256=//p' _COMPLETE)" = "$(sha256sum SHA256SUMS | cut -d ' ' -f 1)"
sha256sum -c SHA256SUMS > /dev/null
"""
    if engine == "clickhouse":
        download = r"""
set -eu
umask 077
export AWS_EC2_METADATA_DISABLED=true
aws --endpoint-url "$S3_ENDPOINT_URL" s3 cp "s3://dbdump/${BACKUP_PREFIX}_COMPLETE" /backup/_COMPLETE --quiet
grep -q '^format=lab-clickhouse-native-v1' /backup/_COMPLETE
"""
    diagnostic = """trap 'result=$?; if [ "$result" -ne 0 ]; then echo RESTORE_DIAGNOSTIC exit=$result; grep -hEo "Code: [0-9]+|ERROR [0-9]+" /work/*.log 2>/dev/null | head -n 5 | sed "s/^/RESTORE_DIAGNOSTIC /"; fi' EXIT
"""
    result = {"apiVersion": "v1", "kind": "Pod", "metadata": {"name": "restore-" + engine, "namespace": namespace}, "spec": {
        "automountServiceAccountToken": False, "restartPolicy": "Never", "activeDeadlineSeconds": 1800,
        "securityContext": {"runAsNonRoot": True, "runAsUser": 999, "runAsGroup": 999, "fsGroup": 999, "seccompProfile": {"type": "RuntimeDefault"}},
        "initContainers": [{"name": "download", "image": uploader, "command": ["sh", "-c", download], "securityContext": security, "volumeMounts": mounts,
                            "env": [{"name": "S3_ENDPOINT_URL", "value": "http://pmhraspberry.tailscale.svc.cluster.local:9000"},
                                    {"name": "BACKUP_PREFIX", "value": prefix}, {"name": "AWS_DEFAULT_REGION", "value": "us-east-1"}, {"name": "HOME", "value": "/tmp"}],
                            "envFrom": [{"secretRef": {"name": "backup-reader"}}]}],
        "containers": [{"name": "restore", "image": native, "command": ["sh", "-c", diagnostic + RESTORE[engine]], "securityContext": security, "volumeMounts": mounts}],
        "volumes": [{"name": n, "emptyDir": {"sizeLimit": "20Gi" if n != "tmp" else "256Mi"}} for n in ["backup", "work", "tmp"]],
    }}
    if engine == "clickhouse":
        result["spec"]["containers"][0]["envFrom"] = [{"secretRef": {"name": "backup-reader"}}]
        result["spec"]["containers"][0]["env"] = [{"name": "BACKUP_PREFIX", "value": prefix}]
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("engines", nargs="+", choices=sorted(RESTORE))
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location("dns01_provision", ROOT / "bootstrap/dns01/provision.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    vault = module.VaultCLI()
    vault.verify()
    credentials = vault.get("database/backpack-secrets")
    client = Minio("127.0.0.1:19000", access_key=credentials["S3_ACCESS_TOKEN"], secret_key=credentials["S3_SECRET_TOKEN"], secure=False, region="us-east-1")
    docs = list(yaml.safe_load_all(subprocess.check_output(["kubectl", "kustomize", str(ROOT / "database")], text=True)))
    namespace = "backup-restore-" + secrets.token_hex(6)
    marker = secrets.token_hex(16)
    kubectl("create", "-f", "-", payload={"apiVersion": "v1", "kind": "Namespace", "metadata": {"name": namespace, "labels": {"lab.pmh.codes/restore-owner": marker}}})
    try:
        kubectl("create", "-f", "-", payload={"apiVersion": "networking.k8s.io/v1", "kind": "NetworkPolicy", "metadata": {"name": "isolate", "namespace": namespace}, "spec": {
            "podSelector": {}, "policyTypes": ["Ingress", "Egress"], "ingress": [], "egress": [
                {"to": [{"namespaceSelector": {"matchLabels": {"kubernetes.io/metadata.name": "kube-system"}}, "podSelector": {"matchLabels": {"k8s-app": "kube-dns"}}}], "ports": [{"protocol": p, "port": 53} for p in ["TCP", "UDP"]]},
                {"to": [{"namespaceSelector": {"matchLabels": {"kubernetes.io/metadata.name": "tailscale"}}}], "ports": [{"protocol": "TCP", "port": 9000}]},
            ]}})
        kubectl("create", "-f", "-", payload={"apiVersion": "v1", "kind": "Secret", "metadata": {"name": "backup-reader", "namespace": namespace}, "type": "Opaque", "data": {
            "AWS_ACCESS_KEY_ID": base64.b64encode(credentials["S3_ACCESS_TOKEN"].encode()).decode(),
            "AWS_SECRET_ACCESS_KEY": base64.b64encode(credentials["S3_SECRET_TOKEN"].encode()).decode(),
        }})
        for engine in args.engines:
            prefix_engine = "pgsql-immich" if engine == "immich" else engine
            complete = sorted(o.object_name.removesuffix("_COMPLETE") for o in client.list_objects("dbdump", prefix=prefix_engine + "/", recursive=True) if o.object_name.endswith("/_COMPLETE"))
            if not complete:
                raise RuntimeError("No completed remote backup is available for " + engine)
            job = next(d for d in docs if d["kind"] == "CronJob" and d["metadata"]["name"] == "backup-" + engine)
            pod = job["spec"]["jobTemplate"]["spec"]["template"]["spec"]
            uploader = pod["containers"][0]["image"]
            if engine == "clickhouse":
                native = next(d for d in docs if d["kind"] == "Deployment" and d["metadata"]["name"] == "clickhouse")["spec"]["template"]["spec"]["containers"][0]["image"]
            else:
                native = pod["initContainers"][0]["image"]
            kubectl("create", "-f", "-", payload=restore_pod(namespace, engine, complete[-1], native, uploader))
            # Wait for termination, including failure, rather than waiting 30m
            # for a Succeeded condition when a restore client rejects the dump.
            import time
            for _ in range(360):
                status = json.loads(kubectl("get", "pod", "restore-" + engine, "-n", namespace, "-o", "json"))["status"]
                if status["phase"] in {"Succeeded", "Failed"}:
                    break
                time.sleep(5)
            if status["phase"] != "Succeeded":
                raw = subprocess.run(["kubectl", "logs", "restore-" + engine, "-n", namespace, "-c", "restore"], text=True, capture_output=True).stdout
                safe = [line for line in raw.splitlines() if re.fullmatch(r"RESTORE_DIAGNOSTIC (exit=\d+|Code: \d+|ERROR \d+)", line)]
                raise RuntimeError("Isolated native restore failed for " + engine + "; " + "; ".join(safe) + "; namespace will be removed")
            output = kubectl("logs", "restore-" + engine, "-n", namespace, "-c", "restore")
            if "RESTORE_OK " + engine not in output:
                raise RuntimeError("Native restore did not return its verification marker")
            print(output.strip())
            print("Remote backup restored without live PVCs or database connectivity: " + complete[-1])
    finally:
        actual = json.loads(kubectl("get", "namespace", namespace, "-o", "json"))
        if actual["metadata"]["labels"].get("lab.pmh.codes/restore-owner") != marker:
            raise RuntimeError("Restore namespace ownership changed; refusing cleanup")
        kubectl("delete", "namespace", namespace, "--wait=true", "--timeout=180s", timeout=190)


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        print("Backup restore check failed: " + str(error) if isinstance(error, RuntimeError) else "Backup restore check failed; details suppressed", file=sys.stderr)
        sys.exit(1)
