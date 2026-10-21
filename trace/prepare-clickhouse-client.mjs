// The pinned upstream client omits CLICKHOUSE_USER. Supplying credentials in
// its shared URL also overrides the separate read-only query identity.
// Preserve the native module and bind only the already-declared main username.
import { createHash } from "node:crypto";
import { readFileSync, writeFileSync } from "node:fs";

const source = readFileSync("/app/dist/db/clickhouse/client.js", "utf8");
const expected = "3c2b3d2cf7ae90715d8783498c940eff75a7a81bbaac6fa5b5a0b4c6c84c507d";
if (createHash("sha256").update(source).digest("hex") !== expected) {
  throw new Error("Pinned native client changed; refusing an unverified compatibility patch");
}
const original = "    database: process.env.CLICKHOUSE_DB,\n    password: process.env.CLICKHOUSE_PASSWORD,";
if (source.split(original).length !== 2) {
  throw new Error("Native main-client configuration is not uniquely identifiable");
}
const updated = "    database: process.env.CLICKHOUSE_DB,\n    username: process.env.CLICKHOUSE_USER,\n    password: process.env.CLICKHOUSE_PASSWORD,";
writeFileSync("/prepared/client.js", source.replace(original, updated), { mode: 0o444 });
console.log("Pinned native main-client username corrected; separate read-only query credentials preserved");
