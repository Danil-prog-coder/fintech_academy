import { baseApi } from '@/shared/api';
import { delay } from '@/shared/lib/time';

import { mockDocuments } from './mockDocuments';
import { type DocumentFile } from '../model/types';

/** Синхронный доступ к каталогу — для демонстрационных AI-сценариев. */
export const getDocumentById = (id: string): DocumentFile | undefined =>
  mockDocuments.find((document) => document.id === id);

export const documentApi = baseApi.injectEndpoints({
  endpoints: (build) => ({
    getDocumentVersions: build.query<DocumentFile[], string>({
      queryFn: async (family) => {
        await delay(300);
        return { data: mockDocuments.filter((document) => document.family === family) };
      },
      providesTags: ['Document'],
    }),
  }),
});

export const { useGetDocumentVersionsQuery } = documentApi;
