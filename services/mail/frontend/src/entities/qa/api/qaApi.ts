import { baseApi } from '@/shared/api';

import {
  type Answer,
  type Escalation,
  type FeedbackRequest,
  type MailAskRequest,
  type MailAskResponse,
} from '../model/types';

export const qaApi = baseApi.injectEndpoints({
  endpoints: (build) => ({
    ask: build.mutation<Answer, { message: string }>({
      query: (body) => ({ url: '/chat/ask', method: 'POST', body }),
    }),
    resetChat: build.mutation<undefined, undefined>({
      query: () => ({ url: '/chat/reset', method: 'POST' }),
    }),
    askAboutDraft: build.mutation<MailAskResponse, MailAskRequest>({
      query: (body) => ({ url: '/mail/ask', method: 'POST', body }),
    }),
    sendFeedback: build.mutation<{ ok: boolean; question_id?: number }, FeedbackRequest>({
      query: (body) => ({ url: '/chat/feedback', method: 'POST', body }),
    }),
    contactSupport: build.mutation<Escalation, { message?: string; request_id?: string }>({
      query: (body) => ({ url: '/support', method: 'POST', body }),
    }),
    getPopular: build.query<{ questions: string[] }, undefined>({
      query: () => '/chat/popular',
    }),
  }),
});

export const {
  useAskMutation,
  useResetChatMutation,
  useAskAboutDraftMutation,
  useSendFeedbackMutation,
  useContactSupportMutation,
  useGetPopularQuery,
} = qaApi;
