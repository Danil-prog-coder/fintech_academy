import {
  type BaseQueryFn,
  createApi,
  type FetchArgs,
  fetchBaseQuery,
  type FetchBaseQueryError,
} from '@reduxjs/toolkit/query/react';

import { env } from '@/shared/config';
import {
  clearTokens,
  getAccessToken,
  getRefreshToken,
  saveTokens,
  type TokenPair,
} from '@/shared/lib/tokens';

const rawBaseQuery = fetchBaseQuery({
  baseUrl: env.apiUrl,
  prepareHeaders: (headers) => {
    const token = getAccessToken();
    if (token) {
      headers.set('authorization', `Bearer ${token}`);
    }
    return headers;
  },
});

let refreshing: Promise<boolean> | null = null;

/** Обновляет пару токенов; параллельные вызовы делят один запрос. */
export const refreshSession = (): Promise<boolean> => {
  refreshing ??= (async () => {
    const refreshToken = getRefreshToken();
    if (!refreshToken) {
      return false;
    }
    try {
      const response = await fetch(`${env.apiUrl}/auth/refresh`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ refresh_token: refreshToken }),
      });
      if (!response.ok) {
        return false;
      }
      saveTokens((await response.json()) as TokenPair);
      return true;
    } catch {
      return false;
    }
  })().finally(() => {
    refreshing = null;
  });
  return refreshing;
};

const isAuthEndpoint = (args: string | FetchArgs) =>
  (typeof args === 'string' ? args : args.url).startsWith('/auth/');

/** При 401 один раз обновляет токены и повторяет запрос; не получилось — выходит из сессии. */
const baseQueryWithReauth: BaseQueryFn<string | FetchArgs, unknown, FetchBaseQueryError> = async (
  args,
  api,
  extraOptions,
) => {
  let result = await rawBaseQuery(args, api, extraOptions);
  if (result.error?.status === 401 && !isAuthEndpoint(args) && getAccessToken()) {
    if (await refreshSession()) {
      result = await rawBaseQuery(args, api, extraOptions);
    } else {
      clearTokens();
    }
  }
  return result;
};

/**
 * Базовый RTK Query API. Эндпоинты добавляются из слайсов через
 * `baseApi.injectEndpoints(...)` в сегменте `api` соответствующего слайса.
 */
export const baseApi = createApi({
  reducerPath: 'api',
  baseQuery: baseQueryWithReauth,
  tagTypes: ['Me', 'Account', 'Folders', 'Messages', 'Message', 'Repo'],
  endpoints: () => ({}),
});
