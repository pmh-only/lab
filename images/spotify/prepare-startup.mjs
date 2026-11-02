// Keep native schema migrations blocking, but do not make HTTP availability
// depend on Spotify's external API during non-schema database maintenance.
import fs from 'node:fs';

const path = '/prepared/index.js';
let source = fs.readFileSync(path, 'utf8');
const migration = '        await Database.startup();';
const listen = '        server.listen(port);';
if (source.split(migration).length === 2 && source.split(listen).length === 2) {
  source = source.replace(migration, '        await Database.detectUpgrade();')
    .replace(listen, listen + `
        // Native repairs retain their locking and error handling, independently
        // of HTTP readiness and external Spotify API rate-limit delays.
        Database.fixMissingTrackData()
            .then(() => Database.deletePossibleDuplicates())
            .catch((error) => logger.error(error));`);
} else {
  console.log('Upstream startup has changed; preserving its native migration and repair handling');
}
fs.writeFileSync(path, source, { mode: 0o444 });
