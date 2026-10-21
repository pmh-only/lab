// Use the native authentication/site lifecycle, never synthesize password hashes
// or reset an existing owner. Signup is enabled only in this isolated Job.
import { readFileSync } from "node:fs";
import { auth } from "/app/dist/lib/auth.js";
import { sql } from "/app/dist/db/postgres/postgres.js";
import { siteConfigurationLifecycle } from "/app/dist/services/sites/siteConfigurationLifecycle.js";
import { initializeCloudTables } from "/app/dist/db/clickhouse/schema/cloud.js";

const read = name => readFileSync("/run/secrets/bootstrap/" + name, "utf8").trim();
const email = read("ADMIN_EMAIL").toLowerCase();
const password = read("ADMIN_PASSWORD");
const name = read("ADMIN_NAME");
const desired = JSON.parse(readFileSync("/bootstrap/bootstrap.json", "utf8"));
const origin = process.env.BASE_URL;
let activeCookies;

function headers(cookies) {
  return new Headers({ origin, ...(cookies ? { cookie: cookies } : {}) });
}

async function logout() {
  if (activeCookies) {
    await auth.api.signOut({ headers: headers(activeCookies) });
    activeCookies = undefined;
  }
}

async function login(method, body) {
  const response = await auth.api[method]({ body, headers: headers(), asResponse: true });
  if (!response.ok) throw new Error("Native authentication request failed; response suppressed");
  activeCookies = response.headers.getSetCookie().map(value => value.split(";")[0]).join("; ");
  if (!activeCookies) throw new Error("Native authentication did not return a session cookie");
  return auth.api.getSession({ headers: headers(activeCookies) });
}

async function main() {
  if (!email.includes("@") || password.length < 48 || !name || origin !== "https://trace.pmh.codes") {
    throw new Error("Invalid managed native bootstrap configuration");
  }
  // The native self-hosted admin overview reads this hourly rollup even though
  // normal startup only creates it in cloud mode. Use the upstream initializer
  // without enabling cloud/billing, altering raw events, or duplicating its SQL.
  await initializeCloudTables();
  let owners = await sql`SELECT id,email,role FROM "user" ORDER BY "createdAt" ASC LIMIT 2`;
  if (owners.length === 0) {
    await login("signUpEmail", { email, password, name });
    await logout();
    owners = await sql`SELECT id,email,role FROM "user" ORDER BY "createdAt" ASC LIMIT 2`;
    console.log("First native account created; upstream admin promotion applied");
  }
  if (owners[0]?.email.toLowerCase() !== email || owners[0]?.role !== "admin") {
    throw new Error("Existing native owner differs; refusing takeover or account reset");
  }
  const session = await login("signInEmail", { email, password });
  if (session?.user?.id !== owners[0].id || session?.user?.role !== "admin") {
    throw new Error("Native owner session could not be verified");
  }
  const existingSites = await sql`SELECT site_id,domain,organization_id FROM sites ORDER BY site_id`;
  let organizationId = existingSites[0]?.organization_id;
  if (!organizationId) {
    const organizations = await sql`SELECT id FROM organization WHERE slug=${desired.organization.slug}`;
    if (organizations.length) organizationId = organizations[0].id;
    else {
      const membership = await sql`SELECT id FROM member WHERE "userId"=${owners[0].id}`;
      if (membership.length) throw new Error("Existing unrelated organization membership; refusing replacement");
      const organization = await auth.api.createOrganization({ body: desired.organization, headers: headers(activeCookies) });
      organizationId = organization.id;
    }
  }
  const membership = await sql`SELECT role FROM member WHERE "organizationId"=${organizationId} AND "userId"=${owners[0].id}`;
  if (membership.length !== 1 || membership[0].role !== "owner") {
    throw new Error("Native bootstrap account is not the organization owner");
  }
  for (const site of desired.sites) {
    const existing = await sql`SELECT site_id,id,domain,organization_id FROM sites WHERE site_id=${site.siteId}`;
    if (existing.length) {
      if (existing[0].domain !== site.domain || existing[0].organization_id !== organizationId || (site.publicId && existing[0].id !== site.publicId)) {
        throw new Error("Existing site differs from declared Gateway bindings; refusing replacement");
      }
      continue;
    }
    const sequence = await sql`SELECT last_value,is_called FROM sites_site_id_seq`;
    const next = Number(sequence[0].last_value) + (sequence[0].is_called ? 1 : 0);
    if (next !== site.siteId) throw new Error("Native site sequence differs; refusing a sequence reset");
    const created = await siteConfigurationLifecycle.create({ name: site.name, domain: site.domain, type: "web", organizationId, createdBy: owners[0].id });
    if (created.siteId !== site.siteId) throw new Error("Native site allocation differed from the declared ID");
    if (site.publicId) {
      // This is a public tracking identifier already declared in the original
      // Gateway, not an old credential. The native API cannot set it. Bind only
      // the newly-created row, guarding its generated ID and empty event state.
      const result = await sql`UPDATE sites SET id=${site.publicId} WHERE site_id=${site.siteId} AND id=${created.id} AND domain=${site.domain}`;
      if (result.count !== 1) throw new Error("New public tracking binding could not be applied safely");
    }
    await siteConfigurationLifecycle.update(site.siteId, site.features);
    console.log("Native site initialized with the original public Gateway binding:", site.siteId, site.domain);
  }
  await logout();
  console.log("Native owner login, organization ownership and declared tracking bindings verified; test sessions invalidated");
}

try {
  await main();
  await sql.end({ timeout: 5 });
  process.exit(0);
} catch (error) {
  try { await logout(); } catch {}
  console.error("Native Rybbit initialization failed; credentials and response bodies suppressed:", error?.name);
  await sql.end({ timeout: 5 });
  process.exit(1);
}
