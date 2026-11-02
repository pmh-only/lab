"""Apply the reviewed native installer corrections once during image build."""
from pathlib import Path
import shutil

installers = list(Path("/opt").glob("seafile/seafile-server-*/setup-seafile-mysql.py"))
if len(installers) != 1:
    raise RuntimeError("Native Seafile installer is not uniquely identifiable")
installer = installers[0]
source = installer.read_text()
patches = {
    "\n    seahub_config.do_syncdb()\n": '\n    if os.environ.get("LAB_SEAFILE_NATIVE_SCHEMA_COMPLETE") != "true":\n        seahub_config.do_syncdb()\n',
}
# Current approved upstream already guards this optional connection. Match full
# lines so a nested native guard cannot accidentally be rewritten a second time.
guarded_close = "\n    if db_config.root_conn:\n        db_config.root_conn.close()\n"
if guarded_close not in source:
    patches["\n    db_config.root_conn.close()\n"] = guarded_close
for before, after in patches.items():
    if source.count(before) != 1:
        raise RuntimeError("Native installer differs from the reviewed compatibility contract")
    source = source.replace(before, after)
compile(source, str(installer), "exec")
target = Path("/opt/lab/installer") / installer.relative_to("/opt")
target.parent.mkdir(parents=True, exist_ok=True)
target.write_text(source)
shutil.copymode(installer, target)
