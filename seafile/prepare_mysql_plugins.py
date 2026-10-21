"""Supply missing native client plugins without weakening MySQL authentication."""

import hashlib
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import urllib.request


URL = "https://ports.ubuntu.com/ubuntu-ports/pool/universe/m/mariadb/libmariadb3_10.11.14-0ubuntu0.24.04.1_arm64.deb"
SHA256 = "ead7fdf6f5fc79a4809db03889763791190973591b872a93c063f5109abfe0ff"
PLUGINS = ["caching_sha2_password.so", "sha256_password.so"]


def main():
    with urllib.request.urlopen(URL, timeout=45) as response:
        archive = response.read(4 * 1024 * 1024 + 1)
    if len(archive) > 4 * 1024 * 1024 or hashlib.sha256(archive).hexdigest() != SHA256:
        raise RuntimeError("Pinned Ubuntu client package checksum mismatch")
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        package = root / "client.deb"
        package.write_bytes(archive)
        subprocess.run(["dpkg-deb", "-x", str(package), str(root / "extracted")], check=True, timeout=30)
        source = root / "extracted/usr/lib/aarch64-linux-gnu/libmariadb3/plugin"
        target = Path("/run/mariadb-client-plugins")
        for name in PLUGINS:
            data = (source / name).read_bytes()
            if data[:6] != b"\x7fELF\x02\x01" or struct.unpack("<H", data[18:20])[0] != 183:
                raise RuntimeError("Client plugin is not an ARM64 ELF shared library")
            shutil.copyfile(source / name, target / name)
            (target / name).chmod(0o644)
    print("Checksum-verified Ubuntu ARM64 SHA2 client plugins prepared; server authentication and bundled client library unchanged")


if __name__ == "__main__":
    main()
