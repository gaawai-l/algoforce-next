import { MutationCache, QueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';

export function isRejection(error) {
  const seen = new Set();
  for (let item = error; item && !seen.has(item); item = item.cause) {
    seen.add(item);
    if (Number(item.code) === 4001 || item.name === 'UserRejectedRequestError' || /user (rejected|denied)|request rejected/i.test(item.message || '')) return true;
  }
  return false;
}
export function notifyFailure(error, stage) {
  const cancelled = {
    connect: 'Connection cancelled. Choose a wallet to try again.',
    switch: 'Network switch cancelled. Choose Base and try again.',
    sign: 'Signature cancelled. Try again when ready.',
  };
  const fallback = {
    connect: 'Could not connect. Open your wallet and try again.',
    switch: 'Could not switch to Base. Check your wallet and try again.',
    sign: 'Could not sign in. Please try again.',
  };
  const message = isRejection(error) ? cancelled[stage] : error?.publicMessage || fallback[stage];
  toast.error(message, { id: 'wallet-error', duration: 5000 });
}
export function createLoginQueryClient() {
  return new QueryClient({ mutationCache: new MutationCache({
    onError(error, _variables, _context, mutation) {
      if (mutation.options.mutationKey?.[0] === 'connect') notifyFailure(error, 'connect');
    },
  }) });
}
