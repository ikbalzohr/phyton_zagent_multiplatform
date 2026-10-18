import fs from 'node:fs/promises';
import { randomBytes, createHash } from 'node:crypto';

const file = new URL('../config/bridge.json', import.meta.url);
const code = randomBytes(24).toString('hex');

await fs.mkdir(new URL('../config/', import.meta.url), { recursive: true });
await fs.writeFile(file, JSON.stringify({
  required: true,
  pairingHash: createHash('sha256').update(code).digest('hex'),
  pairingExpiresAt: Date.now() + 300_000
}, null, 2));

console.log('Bridge protection enabled. Paste this one-use code into the extension within 5 minutes:\n' + code);
console.log('After pairing, trusted local reconnect survives Chrome/Zagent Web restarts until you choose Disconnect.');
