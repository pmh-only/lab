import fs from 'node:fs/promises'
import process from 'node:process'
import path from 'node:path'

const cwd = process.cwd()
const appPath = path.join(cwd, 'apps')
const appNames = await fs
  .readdir(appPath, { withFileTypes: true })
  .then((v) => Promise.all(v
    .filter((v) => v.isFile() && [".yaml", ".yml"].includes(path.extname(v.name)))
    .map((v) => fs.readFile(path.join(appPath, v.name), 'utf-8'))))
  .then((v) => v
    .flatMap((v) => [...v.matchAll(/^\s*name:\s+(\S+)\n[^\n]*?^\s*namespace:/gm)]
    .map((v) => v[1])))

const docsPath = path.join(cwd, 'README.md')
const docs = await fs.readFile(docsPath, 'utf-8')

await fs.writeFile(docsPath, docs
  .replaceAll(
    /<!-- ?SYNC_TABLE_START ?-->[\s\S]*<!-- ?SYNC_TABLE_END ?-->/gm,
    `<!-- SYNC_TABLE_START -->

<table>
  ${appNames.map((v, i) => `
  ${i % 4 === 0 ? '<tr>' : ''}
  <td><img src="https://argo.pmh.codes/api/badge?name=${v}&revision=false&showAppName=true" width="200px" /><br /></td>
  ${i % 4 === 3 ? '</tr>' : ''}
  `).join('')}
</table>

<!-- SYNC_TABLE_END -->`))
