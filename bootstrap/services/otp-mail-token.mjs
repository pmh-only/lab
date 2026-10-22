// Invoke the deployed Mail image's own token/owner functions. This does not
// create accounts, alter passwords/MFA, or read/store synchronized messages.
import fs from "node:fs";
import path from "node:path";

const directory = "/app/build/server/chunks/chunks";
const name = "lab-otp-inbox";

async function native(prefix, symbol) {
  const files = fs.readdirSync(directory).filter(file => file.startsWith(prefix + ".js-") && file.endsWith(".js"));
  if (files.length !== 1) throw new Error("Unexpected native Mail module set");
  const filename = path.join(directory, files[0]);
  const source = fs.readFileSync(filename, "utf8");
  const match = source.match(new RegExp("\\b" + symbol + " as (\\w+)"));
  const module = await import(filename);
  const callable = module[match ? match[1] : symbol];
  if (typeof callable !== "function") throw new Error("Native Mail API export differs");
  return callable;
}

try {
  let input = "";
  for await (const data of process.stdin) input += data;
  const command = JSON.parse(input);
  const initialize = await native("shared-server", "set_private_env");
  initialize(process.env);
  const owner = await (await native("auth-owner", "getAuthUserId"))();
  if (!owner) throw new Error("An existing Mail owner is required; no account will be created");
  const list = await native("api-keys", "listApiKeys");
  let result;
  if (command.mode === "create") {
    if ((await list(owner)).some(key => key.name === name)) throw new Error("Existing OTP key needs coordinated recovery; refusing duplicate issuance");
    const created = await (await native("api-keys", "createApiKey"))(owner, name);
    result = { token: created.key, id: created.id, owner };
  } else if (command.mode === "verify") {
    const verified = await (await native("api-keys", "verifyApiKey"))(command.token);
    if (!verified || verified.userId !== owner) throw new Error("Stored key is not owned by the current Mail owner");
    const row = (await list(owner)).find(key => key.id === verified.id);
    if (row?.name !== name) throw new Error("Stored key is not the dedicated OTP key");
    result = { verified: true };
  } else if (command.mode === "revoke-new") {
    const row = (await list(owner)).find(key => key.id === command.id);
    if (owner !== command.owner || row?.name !== name) throw new Error("Refusing to revoke an unrelated API key");
    result = { revoked: await (await native("api-keys", "revokeApiKey"))(owner, row.id) };
  } else {
    throw new Error("Unsupported native token operation");
  }
  console.log(JSON.stringify(result));
  process.exit(0);
} catch {
  console.error("Native Mail token operation failed; details/credentials suppressed");
  process.exit(1);
}
