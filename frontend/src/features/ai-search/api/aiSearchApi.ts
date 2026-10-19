import { baseApi } from '@/shared/api';
import { delay } from '@/shared/lib/time';

import { runMockSearch } from '../lib/runMockSearch';
import { type SearchRequest, type SearchResult } from '../model/types';

export const SEARCH_DURATION_MS = 2200;

export const aiSearchApi = baseApi.injectEndpoints({
  endpoints: (build) => ({
    aiSearch: build.query<SearchResult, SearchRequest>({
      queryFn: async (request) => {
        await delay(SEARCH_DURATION_MS);
        return { data: runMockSearch(request) };
      },
    }),
  }),
});

export const { useAiSearchQuery } = aiSearchApi;
