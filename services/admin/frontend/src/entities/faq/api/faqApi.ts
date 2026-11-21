import { baseApi } from '@/shared/api';

export interface FaqEntry {
  id: string;
  question: string;
  paraphrases?: string[];
  answer: string | null;
  origin?: string;
  enabled?: boolean;
  served?: number;
  likes?: number;
  dislikes?: number;
}

export const faqApi = baseApi.injectEndpoints({
  endpoints: (build) => ({
    getFaq: build.query<{ entries: FaqEntry[] }, undefined>({
      query: () => '/faq',
      providesTags: ['Faq'],
    }),
    recomputeFaq: build.mutation<unknown, undefined>({
      query: () => ({ url: '/faq/recompute', method: 'POST' }),
      invalidatesTags: ['Faq'],
    }),
    deleteFaq: build.mutation<undefined, string>({
      query: (id) => ({ url: `/faq/${encodeURIComponent(id)}`, method: 'DELETE' }),
      invalidatesTags: ['Faq'],
    }),
  }),
});

export const { useGetFaqQuery, useRecomputeFaqMutation, useDeleteFaqMutation } = faqApi;
