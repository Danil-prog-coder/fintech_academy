import { baseApi } from '@/shared/api';

export interface Stats {
  period_days: number;
  questions: number;
  answered: number;
  answered_share: number | null;
  actions: Record<string, number>;
  cache_hits: number;
  unique_users: number;
  latency_ms_p50: number | null;
  latency_ms_p90: number | null;
  ratings: { up: number; down: number };
  unanswered_pending: number;
  escalations: { open: number; closed: number; by_status: Record<string, number> };
  members: Record<string, number>;
  by_day: ({ date: string; total: number } & Record<string, number | string>)[];
  top_unanswered: string[];
}

export const statsApi = baseApi.injectEndpoints({
  endpoints: (build) => ({
    getStats: build.query<Stats, number>({
      query: (days) => `/stats?days=${String(days)}`,
      providesTags: ['Stats'],
    }),
  }),
});

export const { useGetStatsQuery } = statsApi;
