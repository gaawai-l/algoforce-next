import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { privateKeyToAccount, generatePrivateKey } from 'viem/accounts';
import { createAuth } from '../src/auth.mjs';
import { createServer } from '../src/server.mjs';

test('HTTP enforces origin, secure cookies, login, session, logout and API status', async (t) => {
  const account = privateKeyToAccount(generatePrivateKey());
  const origin = 'https://test.example';
  const auth = await createAuth({ origin, addresses: [account.address], directory: await mkdtemp(join(tmpdir(), 'wallet-http-')) });
  const server = createServer({ auth, origin });
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  t.after(() => new Promise((resolve) => server.close(resolve)));
  const url = `http://127.0.0.1:${server.address().port}`;
  const request = (path, body, cookie, requestOrigin = origin) => fetch(url + path, {
    method: body ? 'POST' : 'GET',
    headers: { Origin: requestOrigin, 'Content-Type': 'application/json', ...(cookie ? { Cookie: cookie } : {}) },
    body: body ? JSON.stringify(body) : undefined,
  });
  let response = await request('/auth/check');
  assert.equal(response.status, 401);
  assert.equal(response.headers.get('www-authenticate'), null);
  assert.equal((await request('/auth/challenge', { address: account.address }, '', 'https://evil.example')).status, 403);
  assert.equal((await request('/auth/challenge', { address: account.address }, '', '')).status, 403);
  assert.equal((await request('/auth/challenge', { address: 'x'.repeat(20_000) })).status, 413);
  response = await request('/auth/challenge', { address: account.address });
  assert.equal(response.status, 200);
  const challengeCookie = response.headers.get('set-cookie');
  assert.match(challengeCookie, /HttpOnly; Secure; SameSite=Lax/);
  const { message } = await response.json();
  response = await request('/auth/verify', { message, signature: await account.signMessage({ message }) }, challengeCookie.split(';')[0]);
  assert.equal(response.status, 200);
  const cookie = response.headers.getSetCookie().find((c) => c.startsWith('__Host-wheelhouse_session=')).split(';')[0];
  assert.equal((await request('/auth/check', null, cookie)).status, 204);
  assert.equal((await (await request('/auth/session', null, cookie)).json()).address, account.address.toLowerCase());
  assert.equal((await request('/auth/logout', {}, cookie)).status, 200);
  assert.equal((await request('/auth/check', null, cookie)).status, 401);
});
