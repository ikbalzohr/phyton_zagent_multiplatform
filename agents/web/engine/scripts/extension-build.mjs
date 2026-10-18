import fs from 'node:fs/promises';
import { spawnSync } from 'node:child_process';
const source = new URL('../extension/', import.meta.url);
const destination = new URL('../artifacts/chrome-bridge/', import.meta.url);
const manifest = JSON.parse(await fs.readFile(new URL('manifest.json', source), 'utf8'));
if (manifest.manifest_version !== 3 || manifest.content_scripts || manifest.externally_connectable) throw new Error('Invalid extension boundary');
await fs.mkdir(destination, { recursive: true });
for (const name of ['manifest.json', 'background.js', 'bridge-config.json', 'popup.html', 'popup.js', 'popup.css']) {
  if (name.endsWith('.js')) {
    const result = spawnSync(process.execPath, ['--check', new URL(name, source).pathname.replace(/^\/([A-Z]:)/, '$1')], { encoding: 'utf8' });
    if (result.status !== 0) throw new Error(result.stderr);
  }
  await fs.copyFile(new URL(name, source), new URL(name, destination));
}
console.log('Validated Manifest V3 unpacked extension: artifacts/chrome-bridge');
