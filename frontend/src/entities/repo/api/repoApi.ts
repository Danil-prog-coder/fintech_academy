import { baseApi } from '@/shared/api';

import { type RepoConnectRequest, type RepoStatusInfo } from '../model/types';

export const POLL_INTERVAL_MS = 3000;

export const repoApi = baseApi.injectEndpoints({
  endpoints: (build) => ({
    getRepoStatus: build.query<RepoStatusInfo, undefined>({
      query: () => '/repo/status',
      providesTags: ['Repo'],
    }),
    connectRepo: build.mutation<RepoStatusInfo, RepoConnectRequest>({
      query: (body) => ({ url: '/repo/connect', method: 'POST', body }),
      invalidatesTags: ['Repo'],
    }),
    disconnectRepo: build.mutation<undefined, undefined>({
      query: () => ({ url: '/repo', method: 'DELETE' }),
      invalidatesTags: ['Repo'],
    }),
  }),
});

export const { useGetRepoStatusQuery, useConnectRepoMutation, useDisconnectRepoMutation } = repoApi;
