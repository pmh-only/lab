import { initializeWebAuth, loadOidcSettings, saveOidcSettings } from '/app/dist/web/auth/session.js';

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
