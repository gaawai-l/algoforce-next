import React from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
const mocks = vi.hoisted(() => ({
  account: { address: undefined, chainId: 8453, isConnected: false },
  sign: vi.fn(), switchChain: vi.fn(), disconnect: vi.fn(), open: vi.fn(),
  toast: vi.fn(), navigate: vi.fn(),
}));
vi.mock('wagmi', () => ({
  useAccount: () => mocks.account,
  useSignMessage: () => ({ signMessageAsync: mocks.sign }),
  useSwitchChain: () => ({ switchChainAsync: mocks.switchChain }),
  useDisconnect: () => ({ disconnect: mocks.disconnect }),
}));
vi.mock('@rainbow-me/rainbowkit', () => ({ useConnectModal: () => ({ openConnectModal: mocks.open }) }));
vi.mock('sonner', () => ({ toast: { error: mocks.toast } }));
import { Login } from '../src/login-page.jsx';
import { createLoginQueryClient } from '../src/notifications.mjs';
const address = '0x11890834531ad1127863895fa83983bfc6347bb0';
function response(body, ok = true, status = ok ? 200 : 401) { return { ok, status, json: async () => body }; }
beforeEach(() => {
  vi.clearAllMocks();
  mocks.account = { address: undefined, chainId: 8453, isConnected: false };
  mocks.sign.mockResolvedValue('0xsigned');
  mocks.switchChain.mockResolvedValue({ id: 8453 });
  vi.stubGlobal('fetch', vi.fn(async (url) => url === '/auth/session' ? response({}, false) : url === '/auth/challenge' ? response({ message: 'Sign in to Sirius' }) : response({})));
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
function connected() { mocks.account = { address, chainId: 8453, isConnected: true }; }

describe('Sirius login', () => {
  it('connects from one button and automatically signs once after connection', async () => {
    const view = render(<Login navigate={mocks.navigate} />);
    const button = await screen.findByRole('button', { name: 'Connect Wallet' });
    await waitFor(() => expect(button.disabled).toBe(false));
    fireEvent.click(button); expect(mocks.open).toHaveBeenCalledOnce();
    connected(); view.rerender(<Login navigate={mocks.navigate} />);
    await waitFor(() => expect(mocks.navigate).toHaveBeenCalledOnce());
    expect(mocks.sign).toHaveBeenCalledExactlyOnceWith({ account: address, message: 'Sign in to Sirius' });
    view.rerender(<Login navigate={mocks.navigate} />);
    expect(mocks.sign).toHaveBeenCalledOnce();
    expect(screen.queryByText('Sign in with wallet')).toBeNull();
  });
  it('shows concise refusal toast without retry loop, and the same button retries', async () => {
    connected(); mocks.sign.mockRejectedValueOnce({ code: 4001, message: 'Verbose wallet internals' });
    render(<Login navigate={mocks.navigate} />);
    await waitFor(() => expect(mocks.toast).toHaveBeenCalledWith('Signature cancelled. Try again when ready.', expect.any(Object)));
    expect(mocks.sign).toHaveBeenCalledOnce(); expect(mocks.navigate).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Connect Wallet' }));
    await waitFor(() => expect(mocks.navigate).toHaveBeenCalledOnce());
    expect(mocks.sign).toHaveBeenCalledTimes(2);
  });
  it('disconnects denied wallets so the connect button can select another wallet', async () => {
    connected();
    fetch.mockImplementation(async (url) => url === '/auth/session' ? response({}, false) : response({ error: 'Not allowed' }, false));
    const view = render(<Login navigate={mocks.navigate} />);
    await waitFor(() => expect(mocks.disconnect).toHaveBeenCalledOnce());
    expect(mocks.toast).toHaveBeenCalledWith('This wallet does not have access to Sirius.', expect.any(Object));
    mocks.account = { address: undefined, chainId: 8453, isConnected: false };
    view.rerender(<Login navigate={mocks.navigate} />);
    fireEvent.click(screen.getByRole('button', { name: 'Connect Wallet' }));
    expect(mocks.open).toHaveBeenCalledOnce();
    expect(mocks.sign).not.toHaveBeenCalled();
  });
  it('keeps existing sessions and never requests a signature', async () => {
    connected(); fetch.mockResolvedValue(response({ address }));
    render(<Login navigate={mocks.navigate} />);
    await waitFor(() => expect(mocks.navigate).toHaveBeenCalledOnce());
    expect(mocks.sign).not.toHaveBeenCalled();
  });
  it('does not authenticate when account changes during a pending signature', async () => {
    connected(); let finish;
    mocks.sign.mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
    const view = render(<Login navigate={mocks.navigate} />);
    await waitFor(() => expect(mocks.sign).toHaveBeenCalledOnce());
    mocks.account = { address: undefined, chainId: undefined, isConnected: false };
    view.rerender(<Login navigate={mocks.navigate} />);
    await act(async () => finish('0xsigned'));
    expect(fetch.mock.calls.filter(([url]) => url === '/auth/verify')).toHaveLength(0);
    expect(mocks.navigate).not.toHaveBeenCalled();
  });
  it('stops on rejected network switch with a retryable notification', async () => {
    connected(); mocks.account.chainId = 1;
    mocks.switchChain.mockRejectedValueOnce({ cause: { code: 4001 } });
    render(<Login navigate={mocks.navigate} />);
    await waitFor(() => expect(mocks.toast).toHaveBeenCalledWith('Network switch cancelled. Choose Base and try again.', expect.any(Object)));
    expect(mocks.sign).not.toHaveBeenCalled();
    expect(mocks.switchChain).toHaveBeenCalledOnce();
  });
  it('surfaces rejected wallet connection even if the modal catches it', async () => {
    const client = createLoginQueryClient();
    const mutation = client.getMutationCache().build(client, { mutationKey: ['connect'], mutationFn: async () => { throw { cause: { code: 4001 } }; } });
    await expect(mutation.execute()).rejects.toBeDefined();
    expect(mocks.toast).toHaveBeenCalledWith('Connection cancelled. Choose a wallet to try again.', expect.any(Object));
  });
});
