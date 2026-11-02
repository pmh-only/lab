"""Apply the reviewed native installer corrections once during image build."""
from pathlib import Path
import shutil

installers = list(Path("/opt").glob("seafile/seafile-server-*/setup-seafile-mysql.py"))
if len(installers) != 1:
    raise RuntimeError("Native Seafile installer is not uniquely identifiable")
installer = installers[0]
source = installer.read_text()
patches = {
    "    db_config.root_conn.close()": "    if db_config.root_conn:\n        db_config.root_conn.close()",
    "    seahub_config.do_syncdb()": '    if os.environ.get("LAB_SEAFILE_NATIVE_SCHEMA_COMPLETE") != "true":\n        seahub_config.do_syncdb()',
}
for before, after in patches.items():
    if source.count(before) != 1:
        raise RuntimeError("Native installer differs from the reviewed compatibility contract")
    source = source.replace(before, after)
compile(source, str(installer), "exec")
target = Path("/opt/lab/installer") / installer.relative_to("/opt")
target.parent.mkdir(parents=True, exist_ok=True)
target.write_text(source)
shutil.copymode(installer, target)
