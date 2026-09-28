import React from 'react';
import { createRoot } from 'react-dom/client';
import { QueryClientProvider } from '@tanstack/react-query';
import { WagmiProvider, createConfig, http } from 'wagmi';
import { base } from 'wagmi/chains';
import { RainbowKitProvider, connectorsForWallets, darkTheme } from '@rainbow-me/rainbowkit';
import { injectedWallet, walletConnectWallet } from '@rainbow-me/rainbowkit/wallets';
import { Toaster } from 'sonner';
import { Login } from './login-page.jsx';
import { createLoginQueryClient } from './notifications.mjs';
import '@rainbow-me/rainbowkit/styles.css';
import './login.css';

const projectId = import.meta.env.VITE_WALLETCONNECT_PROJECT_ID;
const connectors = connectorsForWallets([
  { groupName: 'Your wallets', wallets: [injectedWallet, ...(projectId ? [walletConnectWallet] : [])] },
], { appName: 'Orbit', ...(projectId ? { projectId } : {}) });
const config = createConfig({ chains: [base], connectors, transports: { [base.id]: http() } });
const queryClient = createLoginQueryClient();
createRoot(document.getElementById('root')).render(
  <WagmiProvider config={config}><QueryClientProvider client={queryClient}>
    <RainbowKitProvider locale="en-US" modalSize="compact" initialChain={base} theme={darkTheme({ accentColor: '#5eead4', accentColorForeground: '#051210', borderRadius: 'medium' })}>
      <Login /><Toaster theme="dark" position="bottom-center" richColors closeButton />
    </RainbowKitProvider>
  </QueryClientProvider></WagmiProvider>,
);
