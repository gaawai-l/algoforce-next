import React, { useEffect, useRef, useState } from 'react';
import { useAccount, useDisconnect, useSignMessage, useSwitchChain } from 'wagmi';
import { useConnectModal } from '@rainbow-me/rainbowkit';
import { toast } from 'sonner';
import { notifyFailure } from './notifications.mjs';

async function post(path, body = {}) {
  const response = await fetch(`/auth/${path}`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body), credentials: 'same-origin',
  });
  const result = await response.json();
  if (!response.ok) {
    const error = new Error('Authentication failed');
    error.accessDenied = path === 'challenge' && response.status === 401;
    error.publicMessage = response.status === 429 ? 'Too many attempts. Please wait a minute.'
      : path === 'challenge' && response.status === 401 ? 'This wallet does not have access to Orbit.'
      : 'Could not sign in. Please try again.';
    throw error;
  }
  return result;
}
function destination() {
  const next = new URLSearchParams(location.search).get('next');
  if (next?.startsWith('/') && !next.startsWith('//') && !next.startsWith('/login') && !next.startsWith('/auth')) {
    const target = new URL(next, location.origin);
    if (target.origin === location.origin) return target.pathname + target.search + target.hash;
  }
  return '/market-intelligence';
}
const navigateDefault = (url) => location.replace(url);

function OrbitArt() {
  return <svg className="orbit-art" viewBox="0 0 600 420" role="img" aria-label="Orbit: market paths circling a shared center">
    <defs>
      <radialGradient id="halo"><stop stopColor="#2dd4bf" stopOpacity=".2" /><stop offset="1" stopColor="#2dd4bf" stopOpacity="0" /></radialGradient>
      <linearGradient id="path" x1="0" y1="0" x2="1" y2="1"><stop stopColor="#5eead4" /><stop offset=".5" stopColor="#99f6e4" /><stop offset="1" stopColor="#a78bfa" /></linearGradient>
      <radialGradient id="core" cx=".3" cy=".25"><stop stopColor="#ccfbf1" /><stop offset=".45" stopColor="#5eead4" /><stop offset="1" stopColor="#145e63" /></radialGradient>
    </defs>
    <circle cx="300" cy="210" r="190" fill="url(#halo)" />
    <g fill="none" stroke="#30424f" strokeWidth="1">
      <circle cx="300" cy="210" r="140" strokeDasharray="2 9" />
      <path d="M80 210h440M300 34v352" strokeOpacity=".4" />
      <ellipse cx="300" cy="210" rx="216" ry="81" transform="rotate(-27 300 210)" />
      <ellipse cx="300" cy="210" rx="194" ry="90" transform="rotate(43 300 210)" />
    </g>
    <ellipse cx="300" cy="210" rx="216" ry="81" transform="rotate(-27 300 210)" fill="none" stroke="url(#path)" strokeWidth="2" strokeDasharray="680 300" />
    <ellipse cx="300" cy="210" rx="194" ry="90" transform="rotate(43 300 210)" fill="none" stroke="#a78bfa" strokeOpacity=".6" strokeWidth="1.5" strokeDasharray="310 700" />
    <path d="M143 243l30 9 25-38 26 13 27-44 30 18 33-26 28 12 27-38 29 11 35-29" fill="none" stroke="#5eead4" strokeOpacity=".4" strokeWidth="1.5" />
    <circle cx="300" cy="210" r="36" fill="#5eead4" opacity=".05" />
    <circle cx="300" cy="210" r="22" fill="url(#core)" />
    <circle cx="479" cy="122" r="7" fill="#99f6e4" />
    <circle cx="173" cy="91" r="4" fill="#c4b5fd" />
    <circle cx="112" cy="290" r="3" fill="#5eead4" />
  </svg>;
}

export function Login({ navigate = navigateDefault }) {
  const { address, chainId, isConnected } = useAccount();
  const { disconnect } = useDisconnect();
  const { signMessageAsync } = useSignMessage();
  const { switchChainAsync } = useSwitchChain();
  const { openConnectModal } = useConnectModal();
  const [session, setSession] = useState(null);
  const [checking, setChecking] = useState(true);
  const [busy, setBusy] = useState(false);
  const attempted = useRef(null);
  const pending = useRef(false);
  const identity = isConnected ? address : undefined;
  const current = useRef(identity);
  current.current = identity;
  useEffect(() => {
    let active = true;
    fetch('/auth/session', { cache: 'no-store' }).then(async (response) => {
      if (response.status === 401) return;
      if (!response.ok) throw new Error('Session check failed');
      const data = await response.json();
      if (!active) return;
      setSession(data);
      if (!new URLSearchParams(location.search).has('manage')) navigate(destination());
    }).catch(() => { if (active) toast.error('Unable to check your session. Please try again.', { id: 'wallet-error' }); })
      .finally(() => { if (active) setChecking(false); });
    return () => { active = false; current.current = undefined; };
  }, [navigate]);

  async function login() {
    if (!identity || pending.current || checking || session) return;
    pending.current = true;
    attempted.current = identity;
    setBusy(true);
    let stage = 'switch';
    const stillCurrent = () => current.current === identity;
    try {
      if (chainId !== 8453) await switchChainAsync({ chainId: 8453 });
      if (!stillCurrent()) return;
      stage = 'sign';
      const { message } = await post('challenge', { address: identity });
      if (!stillCurrent()) return;
      const signature = await signMessageAsync({ account: identity, message });
      if (!stillCurrent()) return;
      await post('verify', { message, signature });
      if (!stillCurrent()) { await post('logout'); return; }
      navigate(destination());
    } catch (error) {
      if (stillCurrent()) {
        notifyFailure(error, stage);
        if (error.accessDenied) disconnect();
      }
    } finally { pending.current = false; setBusy(false); }
  }
  useEffect(() => {
    if (!identity) { attempted.current = null; return; }
    if (!checking && !session && !busy && attempted.current !== identity) void login();
  }, [identity, checking, session, busy]);

  async function logout() {
    setBusy(true);
    // Prevent the still-connected wallet from immediately signing in again.
    attempted.current = identity;
    try { await post('logout'); disconnect(); setSession(null); }
    catch (error) { notifyFailure(error, 'sign'); }
    finally { setBusy(false); }
  }
  return <main>
    <section className="login" aria-label="Orbit wallet login">
      <OrbitArt />
      <h1>ORBIT</h1>
      {session ? <div className="session">
        <code>{session.address}</code>
        <a className="primary" href={destination()}>Open workspace</a>
        <button className="secondary" disabled={busy} onClick={logout}>Sign out</button>
      </div> : <button className="primary" disabled={checking || busy || (!identity && !openConnectModal)} onClick={() => identity ? void login() : openConnectModal?.()}>
        {checking ? 'Connecting…' : busy ? 'Confirm in wallet…' : 'Connect Wallet'}
      </button>}
    </section>
  </main>;
}
