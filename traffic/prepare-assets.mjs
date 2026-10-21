// Reuse the GeoIP datasets shipped in the pinned native Rybbit image.
// Do not overwrite existing logs or unfamiliar user-maintained datasets.
import { createHash } from "node:crypto";
import { closeSync, constants, copyFileSync, existsSync, openSync, readFileSync } from "node:fs";

const expected = {
  "GeoLite2-City.mmdb": "95285372ac03ebd0acd1d3fcf0832ffd142e8e0c4b6e8856bb5aa9c47844e539",
  "GeoLite2-ASN.mmdb": "b320d77e002b7454b03d18fca803728a57cfd12428ca39e21bc31fab1b0a5f32",
};
const digest = path => createHash("sha256").update(readFileSync(path)).digest("hex");
for (const [name, checksum] of Object.entries(expected)) {
  const source = "/app/" + name;
  const target = "/logs/" + name;
  if (digest(source) !== checksum) throw new Error("Pinned GeoIP dataset checksum changed: " + name);
  if (!existsSync(target)) copyFileSync(source, target, constants.COPYFILE_EXCL);
  if (digest(target) !== checksum) throw new Error("Existing GeoIP dataset differs; refusing replacement: " + name);
  console.log("Verified packaged GeoIP dataset: " + name);
}
closeSync(openSync("/logs/all.log", "a", 0o640));
console.log("Native log input exists; existing log contents preserved");
