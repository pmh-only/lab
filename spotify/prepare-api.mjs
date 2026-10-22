import fs from 'node:fs';
import { createHash } from 'node:crypto';

const source = fs.readFileSync('/app/apps/server/build/index.js', 'utf8');
const digest = createHash('sha256').update(source).digest('hex');
if (digest !== '79c58a52a835b5b228a5e3ceaeb44b22ae767c3f85ba1f3d596f2818ac6b37af') {
  throw new Error('Unreviewed native YourSpotify bundle; refusing compatibility rewrite');
}
const previous = '/playlists/${id}/tracks';
const replacement = '/playlists/${id}/items';
if (source.split(previous).length !== 2) {
  throw new Error('Native playlist endpoint differs from the reviewed single replacement');
}
// Spotify's February 2026 API migration renamed this endpoint. Preserve the
// native request, OAuth scopes, playlist creation, chunking and track URIs.
fs.writeFileSync('/prepared/index.js', source.replace(previous, replacement), { mode: 0o444 });
console.log('Verified native YourSpotify v1.20.0; only the documented playlist endpoint name updated');
