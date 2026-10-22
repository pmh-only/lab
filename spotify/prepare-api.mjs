import fs from 'node:fs';
import { createHash } from 'node:crypto';

const source = fs.readFileSync('/app/apps/server/build/index.js', 'utf8');
const digest = createHash('sha256').update(source).digest('hex');
if (digest !== '79c58a52a835b5b228a5e3ceaeb44b22ae767c3f85ba1f3d596f2818ac6b37af') {
  throw new Error('Unreviewed native YourSpotify bundle; refusing compatibility rewrite');
}
const previous = '/playlists/${id}/tracks';
const replacement = '/playlists/${id}/items';
const scopeAnchor = '"user-read-recently-played",';
if (source.split(previous).length !== 2 || source.split(scopeAnchor).length !== 2 || source.includes('user-read-currently-playing')) {
  throw new Error('Native playlist endpoint differs from the reviewed single replacement');
}
// Spotify's February 2026 API migration renamed this endpoint. Preserve the
// native request, playlist creation, chunking and track URIs. The paired native
// Playstats frontend also needs the read-only currently-playing OAuth scope.
const prepared = source.replace(previous, replacement).replace(scopeAnchor, scopeAnchor + '\n            "user-read-currently-playing",');
fs.writeFileSync('/prepared/index.js', prepared, { mode: 0o444 });
console.log('Verified native YourSpotify v1.20.0; playlist endpoint and required Playstats read scope updated');
