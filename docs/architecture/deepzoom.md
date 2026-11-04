# High-resolution architecture tiles

- **Viewer**: https://arch.pmh.codes/ — existing OpenSeadragon **4.1.0**; HTML and routing unchanged.
- **Language**: all diagram labels, annotations, and connection labels are in English.
- **High-resolution PNG**: [repository source](./lab-architecture-hires.png) · [deployed image](https://arch.pmh.codes/lab-architecture-hires.png).
- **DZI**: https://arch.pmh.codes/diagram.dzi — preserves the existing viewer's `tileSources` URL.
- **Tiles**: `s3://arch/diagram-be411d78eaf2ec0e_files/` — lossless 512px PNG, 1px overlap, 16 levels, 1,385 tiles.
- **Resolution**: 15,360 × 17,200. Re-rendered from the draw.io XML at 4× scale, not upscaled from the previous PNG.
- **Infrastructure snapshot**: 2026-11-03, not live status. English edition published 2026-11-04.

## Rendering and deployment

To avoid browser truncation of oversized screenshots, the diagram was rendered as a 4×4 grid of 3840×4300 sections using coordinate translation, then composited losslessly. Tiles were generated with Sharp 0.35.5 using `png({compressionLevel:9}).tile({size:512,overlap:1,layout:'dz',depth:'onepixel',skipBlanks:-1})`.

Checks cover tile counts and edge dimensions at every level, pixel identity at full resolution, content in all 16 rendered sections, and label overlaps/clipping. Uploaded object sizes and MD5 hashes are checked against local files, along with public tile samples. Only after verification is `diagram.dzi` switched to the new tile directory. The viewer HTML remains byte-for-byte unchanged. The public viewer is checked at overview and detail zoom levels.

Previous JPG and Korean PNG tile sets are retained. Versioned tiles use a one-year cache lifetime; `diagram.dzi` uses `no-cache,max-age=0,must-revalidate`. Future updates should upload and verify a complete versioned tile set before switching the DZI. No new container, CI workflow, or Kubernetes application is required.

| File | SHA256 |
| --- | --- |
| `lab-architecture.drawio` | `f7d8b9402e446c919048f6949d7bfe600b77dc4b415b066f1d84dcac87f1ed36` |
| `lab-architecture-hires.png` | `be411d78eaf2ec0ed8c665fc4e2a1af88d802b3f77dbe9df7290c898fbb11ad5` |
