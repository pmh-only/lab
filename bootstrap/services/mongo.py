"""Native MongoDB identity provisioning without password resets or data deletion."""

import json
import re
import secrets
import subprocess
import urllib.parse


def spotify_identity(uri):
    value = urllib.parse.urlsplit(uri)
    if (value.scheme != "mongodb" or value.hostname != "mongo-service.database.svc.cluster.local"
            or value.port != 27017 or value.username != "spotify" or value.path != "/your_spotify"
            or value.query != "authSource=your_spotify" or not re.fullmatch(r"[A-Za-z0-9_-]{48,}", value.password or "")):
        raise RuntimeError("Unexpected managed Spotify MongoDB identity")
    return {"username": "spotify", "password": value.password, "database": "your_spotify"}


def shell(code):
    result = subprocess.run(["kubectl", "exec", "-i", "-n", "database", "deployment/mongo", "-c", "mongo", "--",
                             "mongosh", "--quiet", "--file", "/dev/stdin"],
                            input=code, capture_output=True, text=True, timeout=45)
    if result.returncode or "LAB_MONGO_OK" not in result.stdout:
        raise RuntimeError("Native MongoDB operation failed; credential-bearing output suppressed")


def ensure_users(root, uri):
    app = spotify_identity(uri)
    if set(root) != {"username", "password"} or root["username"] != "lab-admin" or len(root["password"]) < 48:
        raise RuntimeError("Unrecognized managed MongoDB administrator identity")
    payload = json.dumps({"root": root, "app": app})
    shell("const input=" + payload + ";\n" + r"""
const admin = db.getSiblingDB('admin');
let authenticated = false;
try { authenticated = admin.auth(input.root.username, input.root.password).ok === 1; }
catch (error) { if (error.code !== 18) throw new Error('Unexpected authentication state'); }
if (!authenticated) {
  const users = admin.runCommand({usersInfo: 1});
  if (users.ok !== 1 || users.users.length !== 0) throw new Error('Existing MongoDB users need manual review');
  const databases = admin.runCommand({listDatabases: 1, nameOnly: true});
  if (databases.ok !== 1) throw new Error('Cannot inspect initial database state');
  for (const database of databases.databases) {
    if (!['admin','local','config'].includes(database.name)) throw new Error('Existing application data requires review');
  }
  admin.createUser({user: input.root.username, pwd: input.root.password,
    roles: [{role:'root', db:'admin'}], customData: {managedBy:'lab-mongo-auth-v1'}});
  if (admin.auth(input.root.username, input.root.password).ok !== 1) throw new Error('Administrator login failed');
}
const actualRoot = admin.getUser(input.root.username);
if (!actualRoot || actualRoot.customData?.managedBy !== 'lab-mongo-auth-v1' || actualRoot.roles.length !== 1 ||
    actualRoot.roles[0].role !== 'root' || actualRoot.roles[0].db !== 'admin') throw new Error('Unrecognized administrator; no changes made');
const application = db.getSiblingDB(input.app.database);
let user = application.getUser(input.app.username);
if (!user) {
  application.createUser({user:input.app.username, pwd:input.app.password,
    roles:[{role:'readWrite', db:input.app.database}], customData:{managedBy:'lab-spotify-v1'}});
  user = application.getUser(input.app.username);
}
if (user.customData?.managedBy !== 'lab-spotify-v1' || user.roles.length !== 1 ||
    user.roles[0].role !== 'readWrite' || user.roles[0].db !== input.app.database) throw new Error('Application privileges differ; refusing takeover');
// Validate the stored password on a separate connection; never update a user.
const endpoint = 'mongodb://' + encodeURIComponent(input.app.username) + ':' + encodeURIComponent(input.app.password) +
  '@127.0.0.1:27017/' + input.app.database + '?authSource=' + input.app.database;
const check = new Mongo(endpoint).getDB(input.app.database);
if (check.runCommand({ping:1}).ok !== 1) throw new Error('Application authentication failed');
print('LAB_MONGO_OK');
""")
    print("mongo: native managed administrator/dedicated Spotify readWrite identity verified; existing data/users/passwords preserved; values suppressed")


def verify_isolation(uri):
    app = spotify_identity(uri)
    probe = "lab_credential_probe_" + secrets.token_hex(12)
    payload = json.dumps({"app": app, "probe": probe})
    shell("const input=" + payload + ";\n" + r"""
const endpoint = 'mongodb://' + encodeURIComponent(input.app.username) + ':' + encodeURIComponent(input.app.password) +
  '@127.0.0.1:27017/' + input.app.database + '?authSource=' + input.app.database;
const application = new Mongo(endpoint).getDB(input.app.database);
const collection = application.getCollection(input.probe);
try {
  collection.insertOne({probe:true});
  if (!collection.findOne({probe:true})) throw new Error('Own-database read failed');
} finally { collection.drop(); }
const foreign = application.getSiblingDB('admin').getCollection(input.probe);
let denied = false;
try { foreign.insertOne({probe:true}); }
catch (error) { if (error.code !== 13) throw error; denied = true; }
if (!denied) { foreign.drop(); throw new Error('Foreign-database write permitted'); }
function unauthorized(action) {
  try { const result = action(); return result.ok === 0 && result.code === 13; }
  catch (error) { if (error.code === 13) return true; throw error; }
}
if (!unauthorized(() => application.getSiblingDB('admin').runCommand({getParameter:1, featureCompatibilityVersion:1}))) throw new Error('Global administration permitted');
let anonymous = new Mongo('mongodb://127.0.0.1:27017/admin');
if (!unauthorized(() => anonymous.getDB('admin').runCommand({listDatabases:1}))) throw new Error('Unauthenticated global access was not denied');
let wrongDenied = false;
try {
  new Mongo('mongodb://spotify:invalid-native-password-check@127.0.0.1:27017/your_spotify?authSource=your_spotify').getDB('your_spotify').runCommand({ping:1});
} catch (error) { if (error.code !== 18) throw error; wrongDenied = true; }
if (!wrongDenied) throw new Error('Wrong password was accepted');
print('LAB_MONGO_OK');
""")
    print("mongo: own DB read/write passed; foreign writes, global administration, anonymous access and wrong passwords denied; only unique probe collection removed")
