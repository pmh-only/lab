import fs from 'node:fs';
import { createHash } from 'node:crypto';

function prepare(path, digest, output, changes) {
  let source = fs.readFileSync(path, 'utf8');
  if (createHash('sha256').update(source).digest('hex') !== digest) {
    throw new Error('Unreviewed native Welplan module; refusing startup rewrite');
  }
  for (const [before, after] of changes) {
    if (source.split(before).length !== 2) throw new Error('Native startup contract differs');
    source = source.replace(before, after);
  }
  fs.writeFileSync('/prepared/' + output, source, { mode: 0o444 });
}

// Preserve dormant legacy data and the user's enabled/disabled subscriptions.
// Leave native table definitions, migrations, indexes and triggers unchanged.
const schemaChanges = [
  ['DROP TABLE IF EXISTS user_selected_restaurants;', '-- Legacy selection data retained.'],
  ['UPDATE webhook_subscriptions SET enabled = TRUE WHERE enabled = FALSE;', '-- Subscription preferences retained.'],
  ['DROP TABLE IF EXISTS menu_review_identity_limits;', '-- Legacy review metadata retained.'],
];
prepare('/app/worker/dist/webapp/src/lib/server/db/index.js',
  '9e0418d0898c93c6121d9a9535b4d4b4de7c370f26aeb585ded2a5866b3d1581', 'worker-db.js', schemaChanges);
prepare('/app/webapp/build/server/chunks/index-BHCbwDKf.js',
  'c3998626e907f227500cc666fee7a998b782bfddd78c760abf7acf2d0aac55a9', 'web-db.js', schemaChanges);
// Reuse the app's real OIDC-backed session gate, not a new Gateway SSO layer.
prepare('/app/webapp/build/server/chunks/hooks.server-CDFvL8tI.js',
  '4a1b57d086ccbdbe599c2202cbae5ec3f2c36fd675770798e285127208004f27', 'hooks.server.js', [[
    'return pathname === "/admin" || pathname.startsWith("/admin/") && !isAdminAuthRoute(pathname);',
    'return pathname === "/api/cache/clear" || pathname === "/admin" || pathname.startsWith("/admin/") && !isAdminAuthRoute(pathname);',
  ]]);
console.log('Verified native Welplan startup modules; data/subscription preferences retained and cache deletion uses existing admin authentication');
