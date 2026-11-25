import { baseApi } from '@/shared/api';
import { type TokenPair } from '@/shared/lib/tokens';

import { type Credentials, type DemoInfo, type Me } from '../model/types';

export const sessionApi = baseApi.injectEndpoints({
  endpoints: (build) => ({
    login: build.mutation<TokenPair, Credentials>({
      query: (body) => ({ url: '/auth/login', method: 'POST', body }),
    }),
    register: build.mutation<TokenPair, Credentials>({
      query: (body) => ({ url: '/auth/register', method: 'POST', body }),
    }),
    getDemoInfo: build.query<DemoInfo, undefined>({
      query: () => '/auth/demo',
    }),
    demoLogin: build.mutation<TokenPair, undefined>({
      query: () => ({ url: '/auth/demo', method: 'POST' }),
    }),
    getMe: build.query<Me, undefined>({
      query: () => '/me',
      providesTags: ['Me'],
    }),
  }),
});

export const {
  useLoginMutation,
  useRegisterMutation,
  useGetMeQuery,
  useGetDemoInfoQuery,
  useDemoLoginMutation,
} = sessionApi;
