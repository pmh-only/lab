#!/usr/bin/env python3
"""Snapshot original artwork into equally padded, self-contained dashboard SVGs.

Run this script to refresh the checked-in assets; deployment does not fetch artwork.
"""

import base64
from pathlib import Path
from urllib.request import urlopen
import xml.etree.ElementTree as ET


DIRECTORY = Path(__file__).resolve().parent
SVG = "http://www.w3.org/2000/svg"
ET.register_namespace("", SVG)
BRANDS = {
    "pdf": "stirling-pdf",
    "seafile": "seafile",
    "immich": "immich",
    "track": "dawarich",
    "tailscale": "tailscale",
    "rustfs": "rustfs",
    "argocd": "argo-cd",
    "technitium": "technitium",
    "kopia": "kopia",
    "velero-ui": "velero",
}
FAVICONS = {
    "books": "https://books.pmh.codes/apple-touch-icon.png",
    "mail": "https://mail.pmh.codes/apple-touch-icon.png",
}
# These applications have no published logo. Use neutral symbols, not invented branding.
SYMBOLS = {
    "go": "link",
    "meta": "chart-no-axes-combined",
    "stmt": "receipt",
    "connect": "network",
    "solver": "calculator",
    "as218822": "network",
    "test": "flask-conical",
}


def download(url):
    with urlopen(url, timeout=30) as response:
        return response.read()


def render(slug, artwork, *, light_background=False, png=False):
    root = ET.Element(f"{{{SVG}}}svg", {
        "width": "80", "height": "80", "viewBox": "0 0 80 80",
    })
    if light_background:
        ET.SubElement(root, f"{{{SVG}}}rect", {
            "x": "4", "y": "4", "width": "72", "height": "72",
            "rx": "12", "fill": "#f8fafc",
        })
    placement = {"x": "14", "y": "14", "width": "52", "height": "52",
                 "preserveAspectRatio": "xMidYMid meet"}
    if png:
        ET.SubElement(root, f"{{{SVG}}}image", {
            **placement, "href": "data:image/png;base64," + base64.b64encode(artwork).decode(),
        })
    else:
        original = ET.fromstring(artwork)
        if "viewBox" not in original.attrib:
            original.set("viewBox", f"0 0 {original.get('width')} {original.get('height')}")
        original.attrib.update(placement)
        root.append(original)
    ET.indent(root, space="  ")
    (DIRECTORY / f"{slug}.svg").write_text(ET.tostring(root, encoding="unicode") + "\n")


def main():
    for slug, brand in BRANDS.items():
        source = f"https://cdn.jsdelivr.net/gh/homarr-labs/dashboard-icons/svg/{brand}.svg"
        render(slug, download(source), light_background=slug in {"tailscale", "rustfs"})
    for slug, source in FAVICONS.items():
        render(slug, download(source), png=True)
    for slug, symbol in SYMBOLS.items():
        source = f"https://cdn.jsdelivr.net/npm/lucide-static@0.468.0/icons/{symbol}.svg"
        artwork = download(source).replace(b'currentColor', b'#334155')
        render(slug, artwork, light_background=True)
    print("Updated 19 icons with original artwork and a shared 52px content area.")


if __name__ == "__main__":
    main()
