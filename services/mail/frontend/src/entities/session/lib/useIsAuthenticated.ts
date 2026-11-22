import { useSyncExternalStore } from 'react';

import { hasTokens, subscribeTokens } from '@/shared/lib/tokens';

/** Есть ли сохранённая сессия; обновляется при входе, выходе и сбое обновления токена. */
export const useIsAuthenticated = () => useSyncExternalStore(subscribeTokens, hasTokens);
