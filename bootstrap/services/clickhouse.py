"""Bootstrap only the new Rybbit database and its separate native SQL identities."""

import base64
from contextlib import contextmanager
import json
import re
import secrets
import select
import subprocess
import threading
import urllib.error
import urllib.parse
import urllib.request


METADATA_COLUMNS = {
    "parts": {"database", "table", "rows", "data_compressed_bytes", "data_uncompressed_bytes", "active", "bytes_on_disk"},
    "query_log": {"event_time", "query_id", "query_kind", "query_duration_ms", "read_rows", "read_bytes", "written_rows", "written_bytes", "memory_usage", "type", "exception_code", "exception", "query", "user", "databases", "tables"},
}


def allowed_writer_grant(grant):
    if grant["database"] == "traffic":
        return not int(grant.get("grant_option", 0))
    return (grant["database"] == "system" and grant.get("access_type") == "SELECT"
            and grant.get("table") in METADATA_COLUMNS
            and grant.get("column") in METADATA_COLUMNS[grant["table"]]
            and not int(grant.get("grant_option", 0)))


def ensure_private_query_log(root):
    # query_log is a native MergeTree table, so native row policies apply.
    engine = root.query("SELECT engine FROM system.tables WHERE database='system' AND name='query_log'")
    if not engine or engine[0]["engine"] != "MergeTree":
        raise RuntimeError("Native query log is not the verified row-policy-capable table")
    names = {"lab_trace_query_log", "lab_trace_query_log_others"}
    existing = root.query("SELECT short_name FROM system.row_policies WHERE database='system' AND table='query_log'")
    if any(r["short_name"] not in names for r in existing):
        raise RuntimeError("Existing query-log policy needs manual review; refusing to weaken it")
    root.query("CREATE ROW POLICY IF NOT EXISTS lab_trace_query_log ON system.query_log FOR SELECT USING user IN ('traffic','traffic_query') TO lab_trace_writer")
    # Preserve visibility for existing/future principals outside this app role.
    root.query("CREATE ROW POLICY IF NOT EXISTS lab_trace_query_log_others ON system.query_log FOR SELECT USING 1 TO ALL EXCEPT lab_trace_writer")
    role_id = root.query("SELECT toString(id) AS id FROM system.roles WHERE name='lab_trace_writer'")[0]["id"]
    role_aliases = {"lab_trace_writer", role_id}
    policies = root.query("SELECT short_name,select_filter,is_restrictive,apply_to_all,apply_to_list,apply_to_except FROM system.row_policies WHERE database='system' AND table='query_log'")
    if len(policies) != 2:
        raise RuntimeError("Unexpected native query-log policy set")
    for policy in policies:
        expression = re.sub(r"[\s`]+", "", policy["select_filter"]).lower()
        if int(policy["is_restrictive"]):
            raise RuntimeError("Unexpected query-log policy mode")
        if policy["short_name"] == "lab_trace_query_log":
            if expression != "userin('traffic','traffic_query')" or int(policy["apply_to_all"]) or policy["apply_to_except"] or len(policy["apply_to_list"]) != 1 or policy["apply_to_list"][0] not in role_aliases:
                raise RuntimeError("Native analytics log policy differs; refusing broad log access")
        else:
            if expression != "1" or not int(policy["apply_to_all"]) or policy["apply_to_list"] or len(policy["apply_to_except"]) != 1 or policy["apply_to_except"][0] not in role_aliases:
                raise RuntimeError("Existing operator query-log visibility could change")


class ClickHouseError(RuntimeError):
    def __init__(self, status, code):
        super().__init__(f"ClickHouse HTTP {status}, code {code}; query and response suppressed")
        self.code = code


class Client:
    def __init__(self, user, password, database=None):
        self.user = user
        self.authorization = "Basic " + base64.b64encode((user + ":" + password).encode()).decode()
        self.database = database

    def query(self, sql):
        params = {"default_format": "JSONEachRow", "log_queries": "0"}
        if self.database:
            params["database"] = self.database
        request = urllib.request.Request("http://127.0.0.1:18123/?" + urllib.parse.urlencode(params),
            data=sql.encode(), headers={"Authorization": self.authorization})
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                body = response.read().decode()
                return [json.loads(line) for line in body.splitlines() if line.strip()]
        except urllib.error.HTTPError as error:
            text = error.read().decode(errors="replace")
            match = re.search(r"Code:\s*(\d+)", text)
            raise ClickHouseError(error.code, int(match[1]) if match else None) from None


@contextmanager
def forwarding():
    process = subprocess.Popen(["kubectl", "port-forward", "-n", "database", "svc/clickhouse-service", "18123:8123", "--address=127.0.0.1"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        if not select.select([process.stdout], [], [], 30)[0] or "Forwarding from" not in process.stdout.readline():
            raise RuntimeError("ClickHouse private API forwarding failed")
        # Keep repeated HTTP requests from blocking kubectl on an unread pipe.
        def drain():
            for _ in process.stdout:
                pass

        threading.Thread(target=drain, daemon=True).start()
        yield
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)


def query_user_statements(password):
    # Exact limits from the pinned native queryUser.js; do not grant the app
    # global user/profile administration just to execute these at startup.
    settings = ", ".join([
        "readonly = 2 READONLY", "max_execution_time = 10 READONLY",
        "max_memory_usage = 4000000000 READONLY", "max_threads = 4 READONLY",
        "max_result_rows = 1000 READONLY", "result_overflow_mode = 'break' READONLY",
        "max_concurrent_queries_for_user = 8 READONLY",
        "max_bytes_before_external_group_by = 2000000000 READONLY",
        "max_bytes_before_external_sort = 2000000000 READONLY",
        "enable_json_type = 1", "log_queries = 0",
    ])
    return [
        "CREATE SETTINGS PROFILE IF NOT EXISTS traffic_query",
        "ALTER SETTINGS PROFILE traffic_query SETTINGS " + settings,
        f"CREATE USER IF NOT EXISTS traffic_query IDENTIFIED WITH sha256_password BY '{password}'",
        f"ALTER USER traffic_query IDENTIFIED WITH sha256_password BY '{password}' SETTINGS PROFILE 'traffic_query'",
        "REVOKE ALL ON *.* FROM traffic_query",
        "GRANT SELECT ON traffic.events TO traffic_query",
    ]


def denied(client, statement, codes):
    try:
        client.query(statement)
    except ClickHouseError as error:
        if error.code not in codes:
            raise
    else:
        raise RuntimeError("ClickHouse negative authorization check unexpectedly succeeded")


def provision(vault, data):
    main_password, query_password = data["CLICKHOUSE_PASSWORD"], data["CLICKHOUSE_QUERY_PASSWORD"]
    if any(not re.fullmatch("[A-Za-z0-9_-]{48,}", value) for value in [main_password, query_password]):
        raise RuntimeError("Unexpected managed ClickHouse credentials")
    root_password = vault.get("database/clickhouse-root-password")["password"]
    with forwarding():
        root = Client("admin", root_password)
        assert root.query("SELECT currentUser() AS name")[0]["name"] == "admin"
        users = {r["name"] for r in root.query("SELECT name FROM system.users")}
        roles = {r["name"] for r in root.query("SELECT name FROM system.roles")}
        databases = {r["name"] for r in root.query("SELECT name FROM system.databases")}
        profiles = {r["name"] for r in root.query("SELECT name FROM system.settings_profiles")}
        expected_roles = {"traffic": "lab_trace_writer", "traffic_query": "lab_trace_query"}
        for user, role in expected_roles.items():
            if user in users:
                grants = root.query(f"SELECT granted_role_name FROM system.role_grants WHERE user_name='{user}'")
                if [r["granted_role_name"] for r in grants] != [role]:
                    raise RuntimeError("Existing ClickHouse identity is not exclusively managed by this bootstrap")
                direct = root.query(f"SELECT access_type,database,table,grant_option FROM system.grants WHERE user_name='{user}'")
                if any(g["database"] != "traffic" or int(g["grant_option"]) or (user == "traffic_query" and (g["access_type"] != "SELECT" or g["table"] != "events")) for g in direct):
                    raise RuntimeError("Existing ClickHouse identity has unrelated direct grants")
        if "traffic_query" in profiles and "traffic_query" not in users:
            raise RuntimeError("Refusing to replace an unowned existing ClickHouse query profile")
        if "traffic" in databases and "traffic" not in users:
            raise RuntimeError("Refusing to take over an existing ClickHouse analytics database")
        for owner, role in expected_roles.items():
            if role in roles:
                assignments = root.query(f"SELECT user_name,role_name FROM system.role_grants WHERE granted_role_name='{role}'")
                if any(r["user_name"] != owner or r["role_name"] not in [None, ""] for r in assignments):
                    raise RuntimeError("Existing ClickHouse role is assigned to an unrelated principal")
                inherited = root.query(f"SELECT count() AS count FROM system.role_grants WHERE role_name='{role}'")
                grants = root.query(f"SELECT access_type,database,table,column,grant_option FROM system.grants WHERE role_name='{role}'")
                if int(inherited[0]["count"]) or any(not allowed_writer_grant(g) if role == "lab_trace_writer" else g["database"] != "traffic" for g in grants):
                    raise RuntimeError("Existing managed ClickHouse role has unexpected broader privileges")
            else:
                root.query("CREATE ROLE " + role)
        if "traffic" not in databases:
            root.query("CREATE DATABASE traffic")
        main = Client("traffic", main_password, "traffic")
        query = Client("traffic_query", query_password, "traffic")
        # Never rotate or repair an unrelated existing password silently.
        for user, client in [("traffic", main), ("traffic_query", query)]:
            if user in users:
                assert client.query("SELECT currentUser() AS name")[0]["name"] == user
        if "traffic" not in users:
            root.query(f"CREATE USER traffic IDENTIFIED WITH sha256_password BY '{main_password}'")
        root.query("GRANT ALL ON traffic.* TO lab_trace_writer")
        root.query("GRANT lab_trace_writer TO traffic")
        root.query("SET DEFAULT ROLE lab_trace_writer TO traffic")
        for statement in query_user_statements(query_password):
            root.query(statement)
        root.query("GRANT lab_trace_query TO traffic_query")
        root.query("SET DEFAULT ROLE lab_trace_query TO traffic_query")
        ensure_private_query_log(root)
        for table, columns in METADATA_COLUMNS.items():
            root.query("GRANT SELECT(" + ",".join(sorted(columns)) + f") ON system.{table} TO lab_trace_writer")
        for user, client, password in [("traffic", main, main_password), ("traffic_query", query, query_password)]:
            assert client.query("SELECT currentUser() AS name")[0]["name"] == user
            denied(Client(user, secrets.token_urlsafe(48), "traffic"), "SELECT 1", {193, 516})
        assert int(query.query("SELECT getSetting('readonly') AS value")[0]["value"]) == 2
        assert int(main.query("SELECT count() AS count FROM system.query_log WHERE user NOT IN ('traffic','traffic_query')")[0]["count"]) == 0
        suffix = secrets.token_hex(8)
        outside = "default.lab_trace_probe_" + suffix
        readonly = "traffic.lab_trace_readonly_probe_" + suffix
        try:
            denied(main, f"CREATE TABLE {outside} (value UInt8) ENGINE=Memory", {497})
            denied(query, f"CREATE TABLE {readonly} (value UInt8) ENGINE=Memory", {164, 497})
        finally:
            root.query("DROP TABLE IF EXISTS " + outside)
            root.query("DROP TABLE IF EXISTS " + readonly)
        print("trace: dedicated ClickHouse writer/read-only identities verified; foreign database writes, read-only writes and wrong passwords rejected")
