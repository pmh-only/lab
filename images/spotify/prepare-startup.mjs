// Keep native schema migrations blocking, but do not make HTTP availability
// depend on Spotify's external API during non-schema database maintenance.
import fs from 'node:fs';

const path = '/prepared/index.js';
let source = fs.readFileSync(path, 'utf8');
const migration = '        await Database.startup();';
const listen = '        server.listen(port);';
for (const anchor of [migration, listen]) {
  if (source.split(anchor).length !== 2) throw new Error('Unreviewed native startup contract');
}
source = source.replace(migration, '        await Database.detectUpgrade();')
  .replace(listen, listen + `
        // Native repairs retain their locking and error handling, independently
        // of HTTP readiness and external Spotify API rate-limit delays.
        Database.fixMissingTrackData()
            .then(() => Database.deletePossibleDuplicates())
            .catch((error) => logger.error(error));`);
fs.writeFileSync(path, source, { mode: 0o444 });
