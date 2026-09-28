// Run only against an isolated test stack with an ephemeral allowlisted account.
import assert from 'node:assert/strict';
import { readFileSync, writeFileSync } from 'node:fs';
import { privateKeyToAccount } from 'viem/accounts';
const [url, origin, accountFile, sessionFile] = process.argv.slice(2);
const account = privateKeyToAccount(JSON.parse(readFileSync(accountFile, 'utf8')).privateKey);
async function request(path, body, cookie) {
  return fetch(url + path, {
    method: body ? 'POST' : 'GET', redirect: 'manual',
    headers: { Origin: origin, 'Content-Type': 'application/json', 'Idempotency-Key': crypto.randomUUID(), ...(cookie ? { Cookie: cookie } : {}) },
    body: body ? JSON.stringify(body) : undefined,
  });
}
let response = await request('/');
assert.equal(response.status, 302);
assert.match(response.headers.get('location'), /\/login\//);
assert.equal(response.headers.get('www-authenticate'), null);
assert.equal((await request('/login/')).status, 200);
for (const endpoint of ['/api/v1/settings', '/api/wheelhouse/v1/status']) assert.equal((await request(endpoint)).status, 401);
response = await request('/auth/challenge', { address: account.address });
assert.equal(response.status, 200);
const challengeCookie = response.headers.get('set-cookie').split(';')[0];
const { message } = await response.json();
response = await request('/auth/verify', { message, signature: await account.signMessage({ message }) }, challengeCookie);
assert.equal(response.status, 200);
const cookie = response.headers.getSetCookie().find((v) => v.startsWith('__Host-wheelhouse_session=')).split(';')[0];
for (const endpoint of ['/', '/api/v1/settings', '/api/wheelhouse/v1/status']) assert.equal((await request(endpoint, null, cookie)).status, 200, endpoint);
assert.equal((await request('/api/wheelhouse/v1/portfolio/sync', {}, cookie)).status, 403);
response = await request('/api/wheelhouse/v1/jobs', { kind: 'refresh', stream: { source: 'fixture', symbol: 'BTCUSDT', timeframe: '1h' }, rules: { demark: {} } }, cookie);
assert.ok(response.status >= 200 && response.status < 300, `Job HTTP ${response.status}: ${await response.text()}`);
writeFileSync(sessionFile, JSON.stringify({ session_cookie: cookie }), { mode: 0o600 });
console.log('Ingress passed: redirect, login page, anonymous API blocking, signed login, both APIs, job creation, broker blocking. Session saved privately for restart verification.');
