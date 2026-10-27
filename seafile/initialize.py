"""Run Seafile's native existing-database setup without giving the app DB root."""

from configparser import ConfigParser
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys


DATA = Path("/shared/seafile")
MARKER = DATA / ".lab-native-bootstrap-v1"
INTEGRATION = Path("/lab-config")


def install_branding(data, integration):
    """Publish immutable public assets without overwriting existing custom files."""
    manifest_path = data / "conf/pmh-drive-brand.json"
    if manifest_path.exists():
        existing = json.loads(manifest_path.read_text())
        if existing.get("managed_by") != "lab/seafile/branding":
            raise RuntimeError("Unmanaged Seafile brand manifest exists; refusing to overwrite")
    destination = data / "seahub-data/custom/pmh-drive"
    destination.mkdir(parents=True, exist_ok=True)
    manifest = {"managed_by": "lab/seafile/branding"}
    for key, filename in {"css": "theme.css", "logo": "logo.svg", "favicon": "icon.svg"}.items():
        content = (integration / filename).read_bytes()
        source = Path(filename)
        name = source.stem + "-" + hashlib.sha256(content).hexdigest()[:16] + source.suffix
        target = destination / name
        if target.exists() and target.read_bytes() != content:
            raise RuntimeError("Existing brand asset differs; refusing to overwrite")
        if not target.exists():
            target.write_bytes(content)
            target.chmod(0o644)
        manifest[key] = "custom/pmh-drive/" + name
    manifest_path.write_text(json.dumps(manifest) + "\n")
    manifest_path.chmod(0o644)
    return manifest


def native_schema_complete(install):
    import pymysql

    manifest = json.loads((INTEGRATION / "native-schema.json").read_text())
    sources = {
        "ccnet_db": [install / "sql/mysql/ccnet.sql"],
        "seafile_db": [install / "sql/mysql/seafile.sql"],
        "seahub_db": [install / "pro/python/seafevents/mysql.sql", install / "seahub/sql/mysql.sql"],
    }
    conn = pymysql.connect(host=os.environ["DB_HOST"], port=int(os.environ["DB_PORT"]),
                           user="seafile", passwd=os.environ["DB_PASSWORD"], charset="utf8mb4", connect_timeout=20)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA IN ('ccnet_db','seafile_db','seahub_db')")
        if cursor.fetchone()[0] == 0:
            return False
        # A previous partial attempt is never blindly re-imported. Fingerprints
        # were verified against isolated databases built from this pinned image.
        for database, files in sources.items():
            names = set()
            for path in files:
                names.update(re.findall(r"(?im)^CREATE\s+TABLE(?:\s+IF\s+NOT\s+EXISTS)?\s+`?([A-Za-z0-9_]+)", path.read_text()))
            if database == "seahub_db":
                names.add("avatar_uploaded")
            pairs = []
            for table in sorted(names):
                cursor.execute(f"SHOW CREATE TABLE `{database}`.`{table}`")
                ddl = re.sub(r" AUTO_INCREMENT=\d+", "", cursor.fetchone()[1]).strip()
                pairs.append((table, ddl))
            digest = hashlib.sha256(json.dumps(pairs, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
            if digest != manifest["databaseSchemaSha256"][database]:
                raise RuntimeError("Existing native schema differs; refusing re-import or reset")
        for table, expected in manifest["fixtureSha256"].items():
            cursor.execute("SELECT COLUMN_NAME FROM information_schema.COLUMNS WHERE TABLE_SCHEMA='seahub_db' AND TABLE_NAME=%s ORDER BY ORDINAL_POSITION", (table,))
            columns = [row[0] for row in cursor.fetchall()]
            select = "JSON_ARRAY(" + ",".join("`" + column + "`" for column in columns) + ")"
            cursor.execute(f"SELECT {select} FROM `seahub_db`.`{table}`")
            rows = sorted(json.dumps(json.loads(row[0]), separators=(",", ":"), ensure_ascii=False) for row in cursor.fetchall())
            if hashlib.sha256("\n".join(rows).encode()).hexdigest() != expected:
                raise RuntimeError("Existing native fixture data differs; refusing re-import or reset")
        print("All three existing native schemas and fixture hashes match the verified pinned-image reference")
        return True
    except pymysql.MySQLError:
        raise RuntimeError("Native schema verification failed; refusing an unverified re-import") from None
    finally:
        conn.close()


def initialize():
    DATA.mkdir(parents=True, exist_ok=True)
    config = DATA / "conf/seafile.conf"
    if not MARKER.exists():
        if config.exists() or (DATA / "seafile-data").exists():
            raise RuntimeError("Existing or partial Seafile data has no managed initialization marker; refusing reinitialization")
        sys.path.insert(0, "/scripts")
        import bootstrap

        schema_complete = native_schema_complete(Path(bootstrap.get_install_dir()))
        installer = Path(bootstrap.get_script("setup-seafile-mysql.py"))
        source = installer.read_text()
        cleanup = "    db_config.root_conn.close()"
        if source.count(cleanup) != 1:
            raise RuntimeError("Pinned native installer cleanup changed; refusing an unverified compatibility patch")
        # 12.0.14 calls close() on an empty root connection even in its supported
        # existing-database mode. Guard only that cleanup in this init container.
        source = source.replace(cleanup, "    if db_config.root_conn:\n        db_config.root_conn.close()")
        schema_import = "    seahub_config.do_syncdb()"
        if source.count(schema_import) != 1:
            raise RuntimeError("Pinned native schema import changed; refusing an unverified compatibility patch")
        source = source.replace(schema_import, '    if os.environ.get("LAB_SEAFILE_NATIVE_SCHEMA_COMPLETE") != "true":\n        seahub_config.do_syncdb()')
        installer.write_text(source)
        original_call = bootstrap.call
        setup = bootstrap.get_script("setup-seafile-mysql.sh")

        def native_call(command, *args, **kwargs):
            if command.startswith(setup + " auto "):
                # The Docker wrapper hardcodes new-database mode. Pass the
                # supported flag to the native installer, leaving its schema
                # and configuration generation entirely upstream-owned.
                env = dict(kwargs["env"])
                env.update({"CCNET_DB": "ccnet_db", "SEAFILE_DB": "seafile_db", "SEAHUB_DB": "seahub_db"})
                env["LAB_SEAFILE_NATIVE_SCHEMA_COMPLETE"] = str(schema_complete).lower()
                result = subprocess.run(command + " --use-existing-db 1", shell=True, env=env,
                                        capture_output=True, timeout=180)
                if result.returncode:
                    diagnostic = (result.stdout + result.stderr).decode(errors="replace")
                    for key, value in {**os.environ, **env}.items():
                        if value and any(part in key.upper() for part in ["PASSWORD", "PASSWD", "SECRET", "TOKEN", "PRIVATE_KEY"]):
                            diagnostic = diagnostic.replace(value, "<redacted>")
                    diagnostic = re.sub(r"\x1b\[[0-9;]*m", "", diagnostic)
                    lines = [line[:400] for line in diagnostic.splitlines() if re.search(r"error|failed|invalid|not found|no such|unknown|usage|argument", line, re.IGNORECASE)]
                    print("Native installer diagnostic:", " | ".join(lines[-5:]) or "nonzero exit without a safe diagnostic")
                    raise RuntimeError("Native existing-database setup failed; installer output suppressed")
                print("Native Seafile schema/configuration initialized using the dedicated three-database identity")
                return 0
            return original_call(command, *args, **kwargs)

        bootstrap.call = native_call
        bootstrap.init_seafile_server()
        if not config.exists() or not (DATA / "seafile-data/current_version").exists():
            raise RuntimeError("Native setup did not create the expected persistent state")
        parser = ConfigParser()
        parser.read(config)
        if parser.get("database", "user") != "seafile":
            raise RuntimeError("Native setup selected an unexpected database identity")
        parser["notification"] = {"enabled": "true", "host": "seafile-noti-service", "port": "8083"}
        with config.open("w") as stream:
            parser.write(stream)
        config.chmod(0o600)
        MARKER.write_text(json.dumps({"nativeVersion": os.environ["SEAFILE_VERSION"], "databaseMode": "existing"}) + "\n")
        MARKER.chmod(0o600)
    else:
        if not config.exists() or not (DATA / "seafile-data/current_version").exists():
            raise RuntimeError("Managed Seafile state is incomplete; refusing reinitialization")
        print("Existing Seafile data, native configuration and user credentials preserved")
    settings = DATA / "conf/seahub_settings.py"
    if not settings.exists():
        raise RuntimeError("Native Seahub configuration is missing")
    plugin = DATA / "conf/seahub_lab.py"
    shutil.copyfile(INTEGRATION / "seahub_lab.py", plugin)
    plugin.chmod(0o644)
    hook = DATA / "conf/seahub_custom_functions.py"
    if (DATA / "conf/seahub_custom_functions").exists() or (
        hook.exists() and not hook.read_text().startswith('"""GitOps-managed Seahub OAuth role hook;')
    ):
        raise RuntimeError("Unmanaged Seahub custom functions exist; refusing to overwrite")
    shutil.copyfile(INTEGRATION / "seahub_custom_functions.py", hook)
    hook.chmod(0o644)
    install_branding(DATA, INTEGRATION)
    text = settings.read_text()
    include = "from seahub_lab import *"
    if include not in text.splitlines():
        with settings.open("a") as stream:
            stream.write("\n# GitOps-managed OAuth/cache integration; native settings above are preserved.\n" + include + "\n")
    settings.chmod(0o600)
    print("Native OAuth/cache integration installed; no DB root credentials are mounted or stored")


if __name__ == "__main__":
    try:
        initialize()
    except (RuntimeError, OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        print(f"Seafile initialization failed: {type(error).__name__}; configuration/credentials suppressed", file=sys.stderr)
        sys.exit(1)
