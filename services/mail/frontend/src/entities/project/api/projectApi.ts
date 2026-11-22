import { baseApi } from '@/shared/api';

import {
  type CreatedProject,
  type JoinedProject,
  type Member,
  type MemberPut,
  type ProjectsResponse,
  type Section,
} from '../model/types';

export const projectApi = baseApi.injectEndpoints({
  endpoints: (build) => ({
    getProjects: build.query<ProjectsResponse, undefined>({
      query: () => '/platform/projects',
      providesTags: ['Projects'],
    }),
    createProject: build.mutation<CreatedProject, { name: string; login: string }>({
      query: (body) => ({ url: '/platform/projects', method: 'POST', body }),
      invalidatesTags: ['Projects'],
    }),
    joinProject: build.mutation<JoinedProject, { project_code: string }>({
      query: (body) => ({ url: '/platform/projects/join', method: 'POST', body }),
      invalidatesTags: ['Projects'],
    }),
    selectProject: build.mutation<{ current_project_id: string }, string>({
      query: (id) => ({ url: `/platform/projects/${id}/select`, method: 'POST' }),
      invalidatesTags: ['Projects'],
    }),
    getMembers: build.query<{ members: Member[]; sections: Section[] }, string>({
      query: (id) => `/platform/projects/${id}/members`,
      providesTags: ['Members'],
    }),
    putMember: build.mutation<
      { member: Member; panel_setup_url?: string },
      { projectId: string; body: MemberPut }
    >({
      query: ({ projectId, body }) => ({
        url: `/platform/projects/${projectId}/members`,
        method: 'PUT',
        body,
      }),
      invalidatesTags: ['Members'],
    }),
    deleteMember: build.mutation<undefined, { projectId: string; email: string }>({
      query: ({ projectId, email }) => ({
        url: `/platform/projects/${projectId}/members/${encodeURIComponent(email)}`,
        method: 'DELETE',
      }),
      invalidatesTags: ['Members'],
    }),
    panelLink: build.mutation<{ panel_setup_url: string }, { projectId: string; email: string }>({
      query: ({ projectId, email }) => ({
        url: `/platform/projects/${projectId}/members/${encodeURIComponent(email)}/panel-link`,
        method: 'POST',
      }),
    }),
  }),
});

export const {
  useGetProjectsQuery,
  useCreateProjectMutation,
  useJoinProjectMutation,
  useSelectProjectMutation,
  useGetMembersQuery,
  usePutMemberMutation,
  useDeleteMemberMutation,
  usePanelLinkMutation,
} = projectApi;
