import { baseApi } from '@/shared/api';

export type Role = 'owner' | 'admin' | 'support';

/** Вошедший аккаунт сайта; проект и роль — когда проект выбран (иначе показываем выбор проекта). */
export interface Me {
  login: string;
  role: Role | null;
  display_name: string | null;
  external_id: string | null;
  project: { id: string; name: string } | null;
}

export interface MyProject {
  id: string;
  name: string;
  role: Role;
  created_at: string;
  current: boolean;
}

export interface Invite {
  project: { id: string; name: string };
  role: Role;
  login_hint: string;
  display_name: string | null;
}

interface Credentials {
  login: string;
  password: string;
}

export const sessionApi = baseApi.injectEndpoints({
  endpoints: (build) => ({
    getMe: build.query<Me, undefined>({ query: () => '/me', providesTags: ['Me'] }),
    register: build.mutation<Me, Credentials>({
      query: (body) => ({ url: '/auth/register', method: 'POST', body }),
      invalidatesTags: ['Me', 'Projects'],
    }),
    login: build.mutation<Me, Credentials>({
      query: (body) => ({ url: '/auth/login', method: 'POST', body }),
      invalidatesTags: ['Me', 'Projects'],
    }),
    logout: build.mutation<undefined, undefined>({
      query: () => ({ url: '/auth/logout', method: 'POST' }),
    }),
    getInvite: build.query<Invite, string>({
      query: (token) => ({ url: '/auth/invite', params: { token } }),
    }),
    claimInvite: build.mutation<Me, { token: string }>({
      query: (body) => ({ url: '/auth/claim', method: 'POST', body }),
    }),
    getMyProjects: build.query<{ projects: MyProject[] }, undefined>({
      query: () => '/projects',
      providesTags: ['Projects'],
    }),
    createProject: build.mutation<Me & { project_code: string }, { name: string }>({
      query: (body) => ({ url: '/projects', method: 'POST', body }),
      invalidatesTags: ['Projects'],
    }),
    joinProject: build.mutation<Me, { project_code: string }>({
      query: (body) => ({ url: '/projects/join', method: 'POST', body }),
      invalidatesTags: ['Projects'],
    }),
    selectProject: build.mutation<Me, string>({
      query: (id) => ({ url: `/projects/${encodeURIComponent(id)}/select`, method: 'POST' }),
    }),
  }),
});

export const {
  useGetMeQuery,
  useRegisterMutation,
  useLoginMutation,
  useLogoutMutation,
  useGetInviteQuery,
  useClaimInviteMutation,
  useGetMyProjectsQuery,
  useCreateProjectMutation,
  useJoinProjectMutation,
  useSelectProjectMutation,
} = sessionApi;
