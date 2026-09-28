import React, { useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { WagmiProvider, createConfig, http, useAccount, useDisconnect, useSignMessage, useSwitchChain } from 'wagmi';
import { base } from 'wagmi/chains';
import { RainbowKitProvider, ConnectButton, connectorsForWallets, darkTheme } from '@rainbow-me/rainbowkit';
import { injectedWallet, walletConnectWallet } from '@rainbow-me/rainbowkit/wallets';
import '@rainbow-me/rainbowkit/styles.css';
import './login.css';

const projectId = import.meta.env.VITE_WALLETCONNECT_PROJECT_ID;
const connectors = connectorsForWallets([
  { groupName: 'Your wallets', wallets: [injectedWallet, ...(projectId ? [walletConnectWallet] : [])] },
], { appName: 'Wheelhouse', ...(projectId ? { projectId } : {}) });
const config = createConfig({ chains: [base], connectors, transports: { [base.id]: http() } });
const queryClient = new QueryClient();

async function post(path, body = {}) {
  const response = await fetch(`/auth/${path}`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body), credentials: 'same-origin',
  });
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || 'Sign-in failed. Please try again.');
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
function Login() {
  const { address, chainId, isConnected } = useAccount();
  const { disconnect } = useDisconnect();
  const { signMessageAsync } = useSignMessage();
  const { switchChainAsync } = useSwitchChain();
  const [session, setSession] = useState(null);
  const [checking, setChecking] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  useEffect(() => {
    let active = true;
    fetch('/auth/session', { cache: 'no-store' }).then(async (response) => {
      if (!response.ok) return;
      const data = await response.json();
      if (!active) return;
      setSession(data);
      if (!new URLSearchParams(location.search).has('manage')) location.replace(destination());
    }).catch(() => { if (active) setError('Unable to check your session. Please try again.'); })
      .finally(() => { if (active) setChecking(false); });
    return () => { active = false; };
  }, []);
  async function login() {
    setBusy(true); setError('');
    try {
      if (chainId !== base.id) await switchChainAsync({ chainId: base.id });
      const { message } = await post('challenge', { address });
      const signature = await signMessageAsync({ message });
      await post('verify', { message, signature });
      location.replace(destination());
    } catch (e) { setError(e.shortMessage || e.message || 'Signature cancelled. Please try again.'); }
    finally { setBusy(false); }
  }
  async function logout() {
    setBusy(true); setError('');
    try { await post('logout'); disconnect(); setSession(null); }
    catch (e) { setError(e.message); }
    finally { setBusy(false); }
  }
  return <main>
    <a className="brand" href="/">WHEELHOUSE<span>Investment workspace</span></a>
    <section className="card" aria-labelledby="login-heading">
      <span className="network"><span /> BASE MAINNET</span>
      <h1 id="login-heading">{session ? 'Your session' : 'Your wallet. Your workspace.'}</h1>
      <p className="intro">{session ? 'You are signed in on this browser.' : 'Connect your approved wallet to access Wheelhouse.'}</p>
      {checking ? <p role="status">Checking your session…</p> : session ? <>
        <code>{session.address}</code>
        <a className="primary" href={destination()}>Open workspace <span aria-hidden="true">↗</span></a>
        <button className="secondary" disabled={busy} onClick={logout}>Sign out of this browser</button>
      </> : <>
        <div className="connect"><ConnectButton accountStatus="address" chainStatus="icon" showBalance={false} /></div>
        {isConnected && <button className="primary" disabled={busy} onClick={login}>{busy ? 'Confirm in your wallet…' : 'Sign in with wallet'}</button>}
        <p className="note">Sign once. Stay signed in for 30 days on this browser.<br />No transaction or gas fee required.</p>
        {!projectId && <p className="help">Use your browser wallet extension or open this page in your wallet’s browser.</p>}
      </>}
      {error && <p className="error" role="alert">{error}</p>}
    </section>
    <footer>Private workspace · Wallet access</footer>
  </main>;
}
createRoot(document.getElementById('root')).render(
  <WagmiProvider config={config}><QueryClientProvider client={queryClient}>
    <RainbowKitProvider locale="en-US" initialChain={base} theme={darkTheme({ accentColor: '#5eead4', accentColorForeground: '#051210', borderRadius: 'medium' })}>
      <Login />
    </RainbowKitProvider>
  </QueryClientProvider></WagmiProvider>,
);
