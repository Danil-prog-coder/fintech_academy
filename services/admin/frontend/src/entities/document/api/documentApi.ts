import { baseApi } from '@/shared/api';

export interface PublishedDoc {
  doc_id: string;
  title: string;
  section: string;
  chunks?: number;
  images?: number;
  source_type?: string;
}

export interface StagedFile {
  name: string;
  section: string;
  size: number;
  modified_at: number;
}

export interface Job {
  job_id: string;
  kind: string;
  status: string;
  created_at: number;
  finished_at?: number | null;
  error?: string | null;
  note?: string | null;
}

export interface Section {
  slug: string;
  title: string;
}

export const documentApi = baseApi.injectEndpoints({
  endpoints: (build) => ({
    getDocuments: build.query<
      { published: { documents: PublishedDoc[]; generation: string | null }; files: StagedFile[] },
      undefined
    >({ query: () => '/documents', providesTags: ['Docs'] }),
    uploadDocuments: build.mutation<{ saved: string[] }, FormData>({
      query: (body) => ({ url: '/documents', method: 'POST', body }),
      invalidatesTags: ['Docs', 'Jobs'],
    }),
    deleteDocument: build.mutation<{ deleted: string[] }, string>({
      query: (id) => ({ url: `/documents/${encodeURIComponent(id)}`, method: 'DELETE' }),
      invalidatesTags: ['Docs', 'Jobs'],
    }),
    reindex: build.mutation<Job, undefined>({
      query: () => ({ url: '/reindex', method: 'POST' }),
      invalidatesTags: ['Jobs'],
    }),
    rollback: build.mutation<{ active_generation: string }, undefined>({
      query: () => ({ url: '/rollback', method: 'POST' }),
      invalidatesTags: ['Docs'],
    }),
    getJobs: build.query<{ jobs: Job[] }, undefined>({
      query: () => '/jobs',
      providesTags: ['Jobs'],
    }),
    getSections: build.query<{ sections: Section[] }, undefined>({
      query: () => '/sections',
      providesTags: ['Sections'],
    }),
    addSection: build.mutation<Section, Section>({
      query: (body) => ({ url: '/sections', method: 'POST', body }),
      invalidatesTags: ['Sections'],
    }),
    deleteSection: build.mutation<undefined, string>({
      query: (slug) => ({ url: `/sections/${slug}`, method: 'DELETE' }),
      invalidatesTags: ['Sections', 'Members'],
    }),
  }),
});

export const {
  useGetDocumentsQuery,
  useUploadDocumentsMutation,
  useDeleteDocumentMutation,
  useReindexMutation,
  useRollbackMutation,
  useGetJobsQuery,
  useGetSectionsQuery,
  useAddSectionMutation,
  useDeleteSectionMutation,
} = documentApi;
