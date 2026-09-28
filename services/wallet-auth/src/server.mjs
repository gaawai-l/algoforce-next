import { createServer as nodeServer } from 'node:http';
import { fileURLToPath } from 'node:url';
import { createAuth, SESSION_SECONDS } from './auth.mjs';

const SESSION = '__Host-wheelhouse_session';
const CHALLENGE = '__Host-wheelhouse_challenge';
const cookie = (name, value, age) => `${name}=${value}; Path=/; Max-Age=${age}; HttpOnly; Secure; SameSite=Lax`;
const readCookie = (req, name) => req.headers.cookie?.split(';').map((v) => v.trim()).find((v) => v.startsWith(name + '='))?.slice(name.length + 1);

export function createServer({ auth, origin }) {
  const attempts = new Map();
  return nodeServer(async (req, res) => {
    res.setHeader('Cache-Control', 'no-store');
    res.setHeader('Content-Type', 'application/json');
    const send = (status, body = {}) => { res.writeHead(status); res.end(status === 204 ? undefined : JSON.stringify(body)); };
    const path = new URL(req.url, 'http://localhost').pathname;
    if (path === '/healthz' && req.method === 'GET') return send(200, { ok: true });
    if (req.method === 'GET' && ['/auth/check', '/auth/session'].includes(path)) {
      const session = auth.session(readCookie(req, SESSION));
      if (!session) return send(401, { error: 'Sign in with your wallet.' });
      return send(path === '/auth/check' ? 204 : 200, session);
    }
    if (req.method !== 'POST') return send(404);
    if (req.headers.origin !== origin) return send(403, { error: 'Same-origin request required.' });
    const minute = Math.floor(Date.now() / 60_000);
    for (const [key, value] of attempts) if (value.minute !== minute) attempts.delete(key);
    const ip = req.headers['x-real-ip'] || req.socket.remoteAddress;
    const rate = attempts.get(ip) || { minute, count: 0 };
    if (rate.count >= 60 || attempts.size >= 5000) return send(429, { error: 'Too many attempts. Please wait a minute.' });
    rate.count++;
    attempts.set(ip, rate);
    let bytes = 0;
    let body = '';
    try {
      for await (const chunk of req) {
        bytes += chunk.length;
        if (bytes > 16_384) { send(413, { error: 'Request too large.' }); return; }
        body += chunk.toString();
      }
      let data;
      try { data = JSON.parse(body); } catch { return send(400, { error: 'Invalid JSON.' }); }
      if (!data || typeof data !== 'object') return send(400);
      if (path === '/auth/challenge') {
        if (typeof data.address !== 'string') return send(400, { error: 'Wallet address required.' });
        const challenge = auth.challenge(data.address);
        res.setHeader('Set-Cookie', cookie(CHALLENGE, challenge.token, 300));
        return send(200, { message: challenge.message });
      }
      if (path === '/auth/verify') {
        const session = await auth.verify({ challenge: readCookie(req, CHALLENGE), message: data.message, signature: data.signature });
        res.setHeader('Set-Cookie', [cookie(SESSION, session.token, SESSION_SECONDS), cookie(CHALLENGE, '', 0)]);
        return send(200, { address: session.address, expires: session.expires });
      }
      if (path === '/auth/logout') {
        await auth.logout(readCookie(req, SESSION));
        res.setHeader('Set-Cookie', [cookie(SESSION, '', 0), cookie(CHALLENGE, '', 0)]);
        return send(200, { ok: true });
      }
      return send(404);
    } catch (error) {
      return send(401, { error: error instanceof Error ? error.message : 'Login failed.' });
    }
  });
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const origin = process.env.WALLET_AUTH_ORIGIN;
  const auth = await createAuth({
    origin, addresses: process.env.WALLET_AUTH_ADDRESSES?.split(',').map((v) => v.trim()).filter(Boolean),
    directory: process.env.WALLET_AUTH_DATA_DIR || '/data', rpcUrl: process.env.BASE_RPC_URL || 'https://mainnet.base.org',
  });
  const server = createServer({ auth, origin });
  server.requestTimeout = 15_000;
  server.headersTimeout = 10_000;
  server.listen(Number(process.env.PORT || 8790), '0.0.0.0');
}
