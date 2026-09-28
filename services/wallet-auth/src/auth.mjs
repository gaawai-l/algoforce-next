import { randomBytes, createHash } from 'node:crypto';
import { mkdirSync, readFileSync, writeFileSync, renameSync } from 'node:fs';
import { join } from 'node:path';
import { createPublicClient, getAddress, http, verifyMessage } from 'viem';
import { base } from 'viem/chains';
import { createSiweMessage } from 'viem/siwe';

export const SESSION_SECONDS = 30 * 86400;
const digest = (value) => createHash('sha256').update(value).digest('hex');
const random = () => randomBytes(32).toString('hex');

export async function createAuth({ origin, addresses, directory, now = Date.now, rpcUrl = 'https://mainnet.base.org' }) {
  const site = new URL(origin);
  if (site.origin !== origin || (site.protocol !== 'https:' && site.hostname !== 'localhost')) throw new Error('Invalid auth origin');
  if (!addresses?.length) throw new Error('Wallet allowlist required');
  const allowed = new Set(addresses.map((address) => getAddress(address.toLowerCase()).toLowerCase()));
  mkdirSync(directory, { recursive: true, mode: 0o700 });
  const filename = join(directory, 'sessions.json');
  let sessions = {};
  try { sessions = JSON.parse(readFileSync(filename, 'utf8')); }
  catch (error) { if (error.code !== 'ENOENT') throw error; }
  const challenges = new Map();
  const client = createPublicClient({ chain: base, transport: http(rpcUrl, { timeout: 8000, retryCount: 0 }) });
  function persist() {
    sessions = Object.fromEntries(Object.entries(sessions).filter(([, s]) => s.expires > now() && allowed.has(s.address)));
    writeFileSync(filename + '.next', JSON.stringify(sessions), { mode: 0o600 });
    renameSync(filename + '.next', filename);
  }
  persist();
  return {
    challenge(address) {
      const normalized = getAddress(address.toLowerCase());
      if (!allowed.has(normalized.toLowerCase())) throw new Error('This wallet is not allowed to access Wheelhouse.');
      for (const [key, value] of challenges) if (value.expires <= now()) challenges.delete(key);
      if (challenges.size >= 500) throw new Error('Too many login attempts. Try again later.');
      const token = random();
      const expires = now() + 5 * 60_000;
      const message = createSiweMessage({
        address: normalized, chainId: 8453, domain: site.host, uri: origin,
        version: '1', nonce: random(), issuedAt: new Date(now()), expirationTime: new Date(expires),
        statement: 'Sign in to Wheelhouse. This does not authorize any transaction.',
      });
      challenges.set(digest(token), { message, address: normalized, expires });
      return { token, message };
    },
    async verify({ challenge, message, signature }) {
      if (typeof challenge !== 'string') throw new Error('Login challenge missing. Reconnect and try again.');
      const key = digest(challenge);
      const saved = challenges.get(key);
      challenges.delete(key);
      if (!saved || saved.expires <= now() || saved.message !== message) throw new Error('Login challenge is invalid or expired. Please try again.');
      const input = { address: saved.address, message, signature };
      let valid = false;
      try { valid = await verifyMessage(input); } catch { /* Contract signatures require RPC verification. */ }
      if (!valid) {
        try { valid = await client.verifyMessage(input); } catch { valid = false; }
      }
      if (!valid) throw new Error('Wallet signature could not be verified.');
      const token = random();
      const session = { address: saved.address.toLowerCase(), expires: now() + SESSION_SECONDS * 1000 };
      sessions[digest(token)] = session;
      persist();
      return { token, ...session };
    },
    session(token) {
      if (typeof token !== 'string' || !/^[a-f0-9]{64}$/.test(token)) return null;
      const session = sessions[digest(token)];
      return session && session.expires > now() && allowed.has(session.address) ? session : null;
    },
    async logout(token) {
      if (typeof token === 'string') { delete sessions[digest(token)]; persist(); }
    },
  };
}
