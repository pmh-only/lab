// Older upstream clients omit CLICKHOUSE_USER. Supplying credentials in
// its shared URL also overrides the separate read-only query identity.
// Preserve the native module and bind only the already-declared main username.
import { readFileSync, writeFileSync } from "node:fs";

const source = readFileSync("/app/dist/db/clickhouse/client.js", "utf8");
const original = "    database: process.env.CLICKHOUSE_DB,\n    password: process.env.CLICKHOUSE_PASSWORD,";
const updated = "    database: process.env.CLICKHOUSE_DB,\n    username: process.env.CLICKHOUSE_USER,\n    password: process.env.CLICKHOUSE_PASSWORD,";
let prepared = source;
if (!/username:\s*process\.env\.CLICKHOUSE_USER\b/.test(source)) {
  if (source.split(original).length !== 2) {
    throw new Error("Native main-client configuration is not uniquely identifiable");
  }
  prepared = source.replace(original, updated);
}
writeFileSync("/prepared/client.js", prepared, { mode: 0o444 });
console.log("Native main-client username configured; separate read-only query credentials preserved");
