import { baseApi } from '@/shared/api';

export interface JiraSettings {
  configured: boolean;
  enabled?: boolean;
  base_url?: string;
  email?: string;
  project_key?: string;
  issue_type?: string;
  webhook_url?: string;
  /** Показывается один раз — при первой настройке и при смене секрета. */
  webhook_secret?: string;
}

export interface JiraInput {
  base_url: string;
  email: string;
  api_token?: string;
  project_key: string;
  issue_type: string;
  enabled: boolean;
}

export const settingsApi = baseApi.injectEndpoints({
  endpoints: (build) => ({
    getProjectCode: build.query<{ code: string | null; issued_at: string }, undefined>({
      query: () => '/project/code',
    }),
    rotateProjectCode: build.mutation<{ code: string }, undefined>({
      query: () => ({ url: '/project/code/rotate', method: 'POST' }),
    }),
    getJira: build.query<JiraSettings, undefined>({ query: () => '/jira', providesTags: ['Jira'] }),
    putJira: build.mutation<JiraSettings, JiraInput>({
      query: (body) => ({ url: '/jira', method: 'PUT', body }),
      invalidatesTags: ['Jira'],
    }),
    rotateJiraSecret: build.mutation<JiraSettings, undefined>({
      query: () => ({ url: '/jira/webhook-secret/rotate', method: 'POST' }),
    }),
    checkJira: build.mutation<
      { ok: boolean; error?: string; project?: { key: string; name: string } },
      undefined
    >({
      query: () => ({ url: '/jira/check', method: 'POST' }),
    }),
  }),
});

export const {
  useGetProjectCodeQuery,
  useRotateProjectCodeMutation,
  useGetJiraQuery,
  usePutJiraMutation,
  useRotateJiraSecretMutation,
  useCheckJiraMutation,
} = settingsApi;
