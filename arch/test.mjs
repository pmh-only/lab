import assert from 'node:assert/strict';
import { readFile, readdir } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import test from 'node:test';
import sharp from 'sharp';

const root = path.dirname(fileURLToPath(import.meta.url));
const dist = path.join(root, 'dist');
const manifest = JSON.parse(await readFile(path.join(dist, 'manifest.json'), 'utf8'));
const dziPath = path.join(dist, manifest.tileSource);
const tiles = dziPath.replace(/\.dzi$/, '_files');

test('DZI describes the full-resolution lossless source', async () => {
  const dzi = await readFile(dziPath, 'utf8');
  assert.match(dzi, /Format="png"/);
  assert.match(dzi, /TileSize="512"/);
  assert.match(dzi, /Overlap="1"/);
  assert.match(dzi, new RegExp(`Width="${manifest.width}"`));
  assert.match(dzi, new RegExp(`Height="${manifest.height}"`));
  assert.equal(manifest.width, 3840 * manifest.renderScale);
  assert.equal(manifest.height, 4300 * manifest.renderScale);
});

test('every pyramid level has all tiles, including white tiles and edge overlaps', async () => {
  const maxLevel = Math.ceil(Math.log2(Math.max(manifest.width, manifest.height)));
  let count = 0;
  for (let level = 0; level <= maxLevel; level++) {
    const divisor = 2 ** (maxLevel - level);
    const width = Math.ceil(manifest.width / divisor);
    const height = Math.ceil(manifest.height / divisor);
    const cols = Math.ceil(width / manifest.tileSize);
    const rows = Math.ceil(height / manifest.tileSize);
    const files = await readdir(path.join(tiles, String(level)));
    assert.equal(files.length, cols * rows, `level ${level}`);
    for (let y = 0; y < rows; y++) {
      for (let x = 0; x < cols; x++) {
        const filename = path.join(tiles, String(level), `${x}_${y}.png`);
        const tile = await sharp(filename).metadata();
        const left = Math.max(0, x * 512 - 1);
        const top = Math.max(0, y * 512 - 1);
        const right = Math.min(width, (x + 1) * 512 + 1);
        const bottom = Math.min(height, (y + 1) * 512 + 1);
        assert.equal(tile.width, right - left, filename);
        assert.equal(tile.height, bottom - top, filename);
        assert.equal(tile.format, 'png', filename);
        count++;
      }
    }
  }
  console.log(`Validated ${count} PNG tiles across ${maxLevel + 1} levels`);
});

test('highest-level tile preserves original pixels exactly', async () => {
  const level = Math.ceil(Math.log2(Math.max(manifest.width, manifest.height)));
  const tile = path.join(tiles, String(level), '10_11.png');
  const { width, height } = await sharp(tile).metadata();
  const original = await sharp(path.join(dist, manifest.image))
    .extract({ left: 10 * 512 - 1, top: 11 * 512 - 1, width, height })
    .removeAlpha().raw().toBuffer();
  const tiled = await sharp(tile).removeAlpha().raw().toBuffer();
  assert.deepEqual(tiled, original);
});

test('all 16 rendered sections contain drawing content, not a truncated blank screenshot', async () => {
  const pixels = await sharp(path.join(dist, manifest.image))
    .resize({ width: 384, height: 430 }).greyscale().raw().toBuffer();
  for (let row = 0; row < 4; row++) {
    for (let col = 0; col < 4; col++) {
      let min = 255;
      let max = 0;
      for (let y = Math.floor(row * 430 / 4); y < Math.floor((row + 1) * 430 / 4); y++) {
        for (let x = col * 96; x < (col + 1) * 96; x++) {
          const value = pixels[y * 384 + x];
          min = Math.min(min, value);
          max = Math.max(max, value);
        }
      }
      assert.ok(max - min > 64, `blank render section ${row},${col}`);
    }
  }
});

test('viewer, vendor script, and editable source are served locally', async () => {
  const html = await readFile(path.join(dist, 'index.html'), 'utf8');
  assert.match(html, /lang="ko"/);
  assert.doesNotMatch(html, /https?:\/\//);
  assert.ok((await readFile(path.join(dist, 'vendor/openseadragon/openseadragon.min.js'))).length > 1000);
  assert.ok((await readFile(path.join(dist, 'vendor/openseadragon/LICENSE.txt'))).length > 0);
  assert.match(await readFile(path.join(dist, manifest.drawing), 'utf8'), /<mxfile/);
});
