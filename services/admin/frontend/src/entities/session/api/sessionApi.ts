import { baseApi } from '@/shared/api';

export type Role = 'owner' | 'admin' | 'support';

export interface Me {
  login: string;
  role: Role;
  display_name: string | null;
  external_id: string;
  project: { id: string; name: string };
}

export const sessionApi = baseApi.injectEndpoints({
  endpoints: (build) => ({
    getMe: build.query<Me, undefined>({ query: () => '/me', providesTags: ['Me'] }),
    login: build.mutation<Me, { login: string; password: string; project_code: string }>({
      query: (body) => ({ url: '/auth/login', method: 'POST', body }),
      invalidatesTags: ['Me'],
    }),
    logout: build.mutation<undefined, undefined>({
      query: () => ({ url: '/auth/logout', method: 'POST' }),
    }),
    setupPassword: build.mutation<
      { login: string; project_name: string | null },
      { token: string; password: string }
    >({
      query: (body) => ({ url: '/auth/setup', method: 'POST', body }),
    }),
  }),
});

export const { useGetMeQuery, useLoginMutation, useLogoutMutation, useSetupPasswordMutation } =
  sessionApi;
