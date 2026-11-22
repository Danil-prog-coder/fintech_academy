import { createApi, fetchBaseQuery } from '@reduxjs/toolkit/query/react';

import { env } from '@/shared/config';

/**
 * API сайта: сессия в httpOnly-cookie (её ставит сервер при входе), поэтому токенов на клиенте нет.
 * Каждый изменяющий запрос несёт заголовок X-Requested-With: panel — без него сервер отвечает 403 (защита от CSRF).
 */
export const baseApi = createApi({
  reducerPath: 'api',
  baseQuery: fetchBaseQuery({
    baseUrl: env.apiUrl,
    credentials: 'include',
    prepareHeaders: (headers) => {
      headers.set('x-requested-with', 'panel');
      return headers;
    },
  }),
  tagTypes: [
    'Me',
    'Projects',
    'Stats',
    'Docs',
    'Jobs',
    'Sections',
    'Members',
    'Questions',
    'Faq',
    'Tickets',
    'Ticket',
    'Jira',
  ],
  endpoints: () => ({}),
});
