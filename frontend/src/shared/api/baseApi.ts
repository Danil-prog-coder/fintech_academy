import { createApi, fetchBaseQuery } from '@reduxjs/toolkit/query/react';

import { env } from '@/shared/config';

/**
 * Базовый RTK Query API. Эндпоинты добавляются из слайсов через
 * `baseApi.injectEndpoints(...)` в сегменте `api` соответствующего слайса.
 */
export const baseApi = createApi({
  reducerPath: 'api',
  baseQuery: fetchBaseQuery({ baseUrl: env.apiUrl }),
  tagTypes: [],
  endpoints: () => ({}),
});
