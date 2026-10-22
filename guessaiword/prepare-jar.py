"""Remove only the compromised packaged configuration; retain native code/assets."""

from pathlib import Path
import zipfile


source = Path('/source/app.jar')
target = Path('/prepared/app.jar')
removed = 'BOOT-INF/classes/application.properties'
with zipfile.ZipFile(source) as original:
    names = original.namelist()
    if names.count(removed) != 1:
        raise RuntimeError('Unreviewed native configuration layout')
    configs = [name for name in names if name.startswith('BOOT-INF/classes/application') and name.endswith(('.properties', '.yml', '.yaml'))]
    if configs != [removed]:
        raise RuntimeError('Additional packaged application configuration requires review')
    if any(name.startswith('META-INF/') and name.upper().endswith(('.SF', '.RSA', '.DSA', '.EC')) for name in names):
        raise RuntimeError('Refusing to invalidate an unreviewed signed application archive')
    with zipfile.ZipFile(target, 'w') as prepared:
        for entry in original.infolist():
            if entry.filename == removed:
                # Do not read, print, extract or copy old credential values.
                continue
            # Preserve ZIP_STORED nested jars as required by Spring Boot 3.0.
            prepared.writestr(entry, original.read(entry.filename))
with zipfile.ZipFile(target) as prepared:
    if removed in prepared.namelist() or len(prepared.namelist()) != len(names) - 1 or prepared.testzip() is not None:
        raise RuntimeError('Prepared native archive integrity verification failed')
target.chmod(0o444)
source.unlink()  # Only the temporary archive copied by this Pod's own init step.
print('Native classes/libraries/dictionaries/frontend retained; old packaged credentials excluded from the runtime archive')
