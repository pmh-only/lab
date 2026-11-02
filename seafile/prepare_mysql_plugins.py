"""Supply missing native client plugins without weakening MySQL authentication."""

from pathlib import Path
import shutil
import struct
import subprocess
import tempfile


PLUGINS = ["caching_sha2_password.so", "sha256_password.so"]


def main():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        # APT authenticates the repository metadata and package hashes. Follow
        # the base distribution instead of freezing one Ubuntu package URL.
        subprocess.run(["apt-get", "download", "libmariadb3"], cwd=root, check=True, timeout=120)
        packages = list(root.glob("libmariadb3_*.deb"))
        if len(packages) != 1:
            raise RuntimeError("Expected one authenticated MariaDB client package")
        package = packages[0]
        subprocess.run(["dpkg-deb", "-x", str(package), str(root / "extracted")], check=True, timeout=30)
        source = root / "extracted/usr/lib/aarch64-linux-gnu/libmariadb3/plugin"
        target = Path("/run/mariadb-client-plugins")
        for name in PLUGINS:
            data = (source / name).read_bytes()
            if data[:6] != b"\x7fELF\x02\x01" or struct.unpack("<H", data[18:20])[0] != 183:
                raise RuntimeError("Client plugin is not an ARM64 ELF shared library")
            shutil.copyfile(source / name, target / name)
            (target / name).chmod(0o644)
    print("Repository-verified ARM64 SHA2 client plugins prepared; server authentication and bundled client library unchanged")


if __name__ == "__main__":
    main()
