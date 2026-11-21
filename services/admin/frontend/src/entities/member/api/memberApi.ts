import { baseApi } from '@/shared/api';

export interface Member {
  external_id: string;
  role: 'owner' | 'admin' | 'support' | 'user';
  display_name: string | null;
  allowed_sections: string[] | null;
  panel_login: string | null;
  panel_password_set: boolean;
  created_at: string;
}

export interface MemberPatch {
  role?: 'admin' | 'support' | 'user';
  login?: string;
  display_name?: string;
  allowed_sections?: string[] | null;
  set_sections?: boolean;
}

export const memberApi = baseApi.injectEndpoints({
  endpoints: (build) => ({
    getMembers: build.query<{ members: Member[] }, undefined>({
      query: () => '/members',
      providesTags: ['Members'],
    }),
    patchMember: build.mutation<
      { member: Member; panel_setup_url?: string },
      { externalId: string; body: MemberPatch }
    >({
      query: ({ externalId, body }) => ({
        url: `/members/${encodeURIComponent(externalId)}`,
        method: 'PATCH',
        body,
      }),
      invalidatesTags: ['Members'],
    }),
    deleteMember: build.mutation<undefined, string>({
      query: (externalId) => ({
        url: `/members/${encodeURIComponent(externalId)}`,
        method: 'DELETE',
      }),
      invalidatesTags: ['Members'],
    }),
    passwordReset: build.mutation<{ panel_setup_url: string }, string>({
      query: (externalId) => ({
        url: `/members/${encodeURIComponent(externalId)}/password-reset`,
        method: 'POST',
      }),
    }),
  }),
});

export const {
  useGetMembersQuery,
  usePatchMemberMutation,
  useDeleteMemberMutation,
  usePasswordResetMutation,
} = memberApi;
