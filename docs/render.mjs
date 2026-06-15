import fs from 'node:fs/promises'
import process from 'node:process'
import path from 'node:path'

const apiURL = 'https://argo.pmh.codes/api/v1/applications?fields=items.metadata.name'

const appNames = await fetch(apiURL)
  .then((res) => res.json())
  .then((res) => res.items.map((v) => v.metadata.name))
  
const cwd = process.cwd()
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
