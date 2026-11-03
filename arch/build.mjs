import { createHash } from 'node:crypto';
import { cp, mkdir, readFile, writeFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import sharp from 'sharp';

const root = path.dirname(fileURLToPath(import.meta.url));
const source = path.resolve(root, '../docs/architecture');
const output = path.join(root, 'dist');
const image = path.join(source, 'lab-architecture-hires.png');
const hash = (data) => createHash('sha256').update(data).digest('hex');
const provenance = JSON.parse(await readFile(path.join(root, 'source.json'), 'utf8'));
const imageHash = hash(await readFile(image));
const drawingHash = hash(await readFile(path.join(source, 'lab-architecture.drawio')));
if (imageHash !== provenance.pngSha256 || drawingHash !== provenance.drawioSha256) {
  throw new Error('Source changed: re-render the draw.io at 4× and update arch/source.json.');
}

sharp.cache({ memory: 128 });
sharp.concurrency(2);
const { width, height } = await sharp(image).metadata();
if (width !== provenance.width || height !== provenance.height) {
  throw new Error('Unexpected source image dimensions.');
}

const version = imageHash.slice(0, 16);
const assets = path.join(output, 'assets', version);
await mkdir(assets, { recursive: true });
await cp(path.join(root, 'site'), output, { recursive: true });
await cp(path.join(root, 'node_modules/openseadragon/build/openseadragon'),
  path.join(output, 'vendor/openseadragon'), { recursive: true });
await cp(path.join(root, 'node_modules/openseadragon/LICENSE.txt'),
  path.join(output, 'vendor/openseadragon/LICENSE.txt'));
await sharp(image)
  .removeAlpha()
  .png({ compressionLevel: 9 })
  .tile({ size: 512, overlap: 1, layout: 'dz', depth: 'onepixel', skipBlanks: -1 })
  .toFile(path.join(assets, 'architecture.dz'));
await cp(image, path.join(assets, 'architecture.png'));
await cp(path.join(source, 'lab-architecture.drawio'), path.join(assets, 'architecture.drawio'));
await writeFile(path.join(output, 'manifest.json'), JSON.stringify({
  width, height, tileSize: 512, overlap: 1, format: 'png',
  tileSource: `/assets/${version}/architecture.dzi`,
  image: `/assets/${version}/architecture.png`,
  drawing: `/assets/${version}/architecture.drawio`,
  ...provenance,
}, null, 2) + '\n');
console.log(`Built ${width}×${height} lossless Deep Zoom pyramid: ${version}`);
