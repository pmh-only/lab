// Use the exact schema revision embedded in the pinned ARM64 application image.
// Its published migrator image is amd64-only, so run the same Prisma CLI natively.
const { spawnSync } = require('node:child_process');
const fs = require('node:fs');
const crypto = require('node:crypto');

function command(program, args, options = {}) {
  const result = spawnSync(program, args, { stdio: 'inherit', ...options });
  if (result.status !== 0) process.exit(result.status || 1);
}

async function main() {
  command('apk', ['add', '--no-cache', 'openssl']);
  const root = '/tmp/keysboard-migrations';
  fs.mkdirSync(`${root}/prisma/migrations/0_init`, { recursive: true });
  const revision = 'b90e6d723413f7bdb7fe150268bdea0f873acc0f';
  const files = {
    'prisma/schema.prisma': '583d8befa496bb91fefd56561b94eff6e04e7504a8bf7729e5b24b570997adb8',
    'prisma/migrations/0_init/migration.sql': '2024131f5206499a77a48e337d3eee323790c3a5296c3ef6ff91507c92a1b7b6',
  };
  for (const [path, expected] of Object.entries(files)) {
    const response = await fetch(`https://raw.githubusercontent.com/pmh-only/keysboard/${revision}/${path}`);
    if (!response.ok) throw new Error('Pinned migration source download failed');
    const data = Buffer.from(await response.arrayBuffer());
    if (crypto.createHash('sha256').update(data).digest('hex') !== expected) {
      throw new Error('Pinned migration source checksum mismatch');
    }
    fs.writeFileSync(`${root}/${path}`, data);
  }
  command('npx', ['--yes', 'prisma@5.6.0', 'migrate', 'deploy', '--schema', 'prisma/schema.prisma'], { cwd: root });
}

main().catch(() => {
  console.error('Keysboard migration failed; credentials are not printed.');
  process.exit(1);
});
