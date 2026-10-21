"""Run Seafile's native existing-database setup without giving the app DB root."""

from configparser import ConfigParser
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


DATA = Path("/shared/seafile")
MARKER = DATA / ".lab-native-bootstrap-v1"
INTEGRATION = Path("/lab-config")


def initialize():
    DATA.mkdir(parents=True, exist_ok=True)
    config = DATA / "conf/seafile.conf"
    if not MARKER.exists():
        if config.exists() or (DATA / "seafile-data").exists():
            raise RuntimeError("Existing or partial Seafile data has no managed initialization marker; refusing reinitialization")
        sys.path.insert(0, "/scripts")
        import bootstrap

        original_call = bootstrap.call
        setup = bootstrap.get_script("setup-seafile-mysql.sh")

        def native_call(command, *args, **kwargs):
            if command.startswith(setup + " auto "):
                # The Docker wrapper hardcodes new-database mode. Pass the
                # supported flag to the native installer, leaving its schema
                # and configuration generation entirely upstream-owned.
                env = dict(kwargs["env"])
                env.update({"CCNET_DB": "ccnet_db", "SEAFILE_DB": "seafile_db", "SEAHUB_DB": "seahub_db"})
                result = subprocess.run(command + " --use-existing-db 1", shell=True, env=env,
                                        capture_output=True, timeout=180)
                if result.returncode:
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
