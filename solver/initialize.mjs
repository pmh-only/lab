import fs from 'node:fs';
import { createHash } from 'node:crypto';
import { initializeWebAuth, loadOidcSettings, saveOidcSettings } from '/app/dist/web-auth.js';

// Keep the original application and its native session/CSRF/authentication flow.
// Require the existing authorization flags before exposing authenticated APIs.
const path = '/app/dist/web-server.js';
let source = fs.readFileSync(path, 'utf8');
if (createHash('sha256').update(source).digest('hex') !== '763d32ab0571673f0b3c3c4ef0f254422044861904a420cfbb6abfc446125f9f') {
  throw new Error('Unreviewed Solver web module; refusing startup rewrite');
}
const before = `function authenticated(request, response) {
    const session = getWebSession(request);
    if (!session)
        sendJson(response, 401, { error: 'Authentication required' });
    return session;
}`;
const after = `function authenticated(request, response) {
    const session = getWebSession(request);
    if (!session) {
        sendJson(response, 401, { error: 'Authentication required' });
        return null;
    }
    if (!session.user.allowed) {
        sendJson(response, 403, { error: 'Web assistant access is not allowed for this identity' });
        return null;
    }
    const path = new URL(request.url || '/', 'http://solver.invalid').pathname;
    if (path.startsWith('/api/admin/') && !session.user.admin) {
        sendJson(response, 403, { error: 'Administrator access required' });
        return null;
    }
    return session;
}`;
if (source.split(before).length !== 2) throw new Error('Native Solver session contract differs');
source = source.replace(before, after);
fs.writeFileSync('/prepared/web-server.js', source, { mode: 0o444 });

// Initialize only configuration, before any HTTP listener, Discord or AI work.
// Preserve subsequent settings made through the original native web interface.
initializeWebAuth();
if (!loadOidcSettings()) {
  const subjects = process.env.WEB_ADMIN_SUBJECTS;
  if (!subjects) throw new Error('Existing human administrator subjects are required');
  saveOidcSettings({
    enabled: true,
    issuerUrl: 'https://auth.pmh.codes/application/o/solver/',
    clientId: 'lab-solver',
    clientSecret: process.env.OIDC_CLIENT_SECRET,
    redirectUri: 'https://solver.pmh.codes/auth/callback',
    scopes: 'openid profile email',
    automaticLogin: true,
    postLogoutRedirectUri: '',
    allowedSubjects: subjects,
    adminSubjects: subjects,
  });
}
console.log('Native encrypted OIDC settings initialized/preserved before startup; existing session flags protect APIs/admin configuration');
