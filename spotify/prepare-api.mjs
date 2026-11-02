import fs from 'node:fs';

let source = fs.readFileSync('/app/apps/server/build/index.js', 'utf8');
const previous = '/playlists/${id}/tracks';
const replacement = '/playlists/${id}/items';
const scopeAnchor = '"user-read-recently-played",';
const proxyAnchor = 'const app = express_default()();';
// Spotify's February 2026 API migration renamed this endpoint. Preserve the
// native request, playlist creation, chunking and track URIs. The paired native
// Playstats frontend also needs the read-only currently-playing OAuth scope.
if (source.includes(previous)) {
  if (source.split(previous).length !== 2) throw new Error('Playlist endpoint is ambiguous');
  source = source.replace(previous, replacement);
}
if (!source.includes('user-read-currently-playing')) {
  if (source.split(scopeAnchor).length !== 2) throw new Error('OAuth scopes are not uniquely identifiable');
  source = source.replace(scopeAnchor, scopeAnchor + '\n            "user-read-currently-playing",');
}
// Do not rewrite native handling if upstream already configures the proxy.
if (!/\.set\(["']trust proxy["']/.test(source)) {
  if (source.split(proxyAnchor).length !== 2) throw new Error('Express application is not uniquely identifiable');
  source = source.replace(proxyAnchor, proxyAnchor + '\napp.set("trust proxy", 1);');
}
fs.writeFileSync('/prepared/index.js', source, { mode: 0o444 });
console.log('Native playlist/read-scope compatibility and trusted HTTPS cookie scheme prepared');
