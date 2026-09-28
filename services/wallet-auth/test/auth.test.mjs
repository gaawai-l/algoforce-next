import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { generatePrivateKey, privateKeyToAccount } from 'viem/accounts';
import { createAuth } from '../src/auth.mjs';

const origin = 'https://test.example';
async function fixture() {
  const account = privateKeyToAccount(generatePrivateKey());
  const directory = await mkdtemp(join(tmpdir(), 'wallet-auth-'));
  let now = Date.now();
  const options = { origin, addresses: [account.address], directory, now: () => now };
  const auth = await createAuth(options);
  return { account, auth, options, advance: (ms) => { now += ms; } };
}
async function sign(f, change = (m) => m) {
  const challenge = f.auth.challenge(f.account.address);
  const message = change(challenge.message);
  const signature = await f.account.signMessage({ message });
  return { challenge: challenge.token, message, signature };
}

test('signed allowlisted wallet gets persistent session and logout revokes it', async () => {
  const f = await fixture();
  const login = await f.auth.verify(await sign(f));
  assert.equal(f.auth.session(login.token).address, f.account.address.toLowerCase());
  const restarted = await createAuth(f.options);
  assert.equal(restarted.session(login.token).address, f.account.address.toLowerCase());
  await restarted.logout(login.token);
  assert.equal(restarted.session(login.token), null);
  assert.equal((await createAuth(f.options)).session(login.token), null);
});

test('rejects non-allowlisted wallets and invalid addresses', async () => {
  const f = await fixture();
  assert.throws(() => f.auth.challenge(privateKeyToAccount(generatePrivateKey()).address));
  assert.throws(() => f.auth.challenge('not-an-address'));
});

test('rejects changed domain, chain, nonce and invalid signature', async () => {
  const f = await fixture();
  for (const change of [
    (m) => m.replace('test.example', 'evil.example'),
    (m) => m.replace('Chain ID: 8453', 'Chain ID: 1'),
    (m) => m.replace(/Nonce: .+/, 'Nonce: wrongnonce'),
  ]) {
    await assert.rejects(f.auth.verify(await sign(f, change)));
  }
  const signed = await sign(f);
  signed.signature = await privateKeyToAccount(generatePrivateKey()).signMessage({ message: signed.message });
  await assert.rejects(f.auth.verify(signed));
});

test('challenge is browser bound, single use, and consumed even on invalid verification', async () => {
  const f = await fixture();
  const signed = await sign(f);
  await assert.rejects(f.auth.verify({ ...signed, challenge: 'other-browser' }));
  await f.auth.verify(signed);
  await assert.rejects(f.auth.verify(signed));
  const invalid = await sign(f);
  await assert.rejects(f.auth.verify({ ...invalid, signature: '0x00' }));
  await assert.rejects(f.auth.verify(invalid));
});

test('expired challenges and sessions are rejected', async () => {
  const f = await fixture();
  const expired = await sign(f);
  f.advance(6 * 60_000);
  await assert.rejects(f.auth.verify(expired));
  const login = await f.auth.verify(await sign(f));
  f.advance(31 * 86400_000);
  assert.equal(f.auth.session(login.token), null);
});

test('fails closed without origin or wallet allowlist', async () => {
  const f = await fixture();
  await assert.rejects(createAuth({ ...f.options, addresses: [] }));
  await assert.rejects(createAuth({ ...f.options, origin: '' }));
});
