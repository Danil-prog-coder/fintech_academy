import { baseApi } from '@/shared/api';

import {
  type AnswerResponse,
  type AskRequest,
  type Conversation,
  type FeedbackRequest,
  type MailAskRequest,
  type MailAskResponse,
  type Source,
} from '../model/types';

export const qaApi = baseApi.injectEndpoints({
  endpoints: (build) => ({
    ask: build.mutation<AnswerResponse, AskRequest>({
      query: (body) => ({ url: '/qa/ask', method: 'POST', body }),
    }),
    getConversation: build.query<Conversation, number>({
      query: (id) => `/qa/conversations/${String(id)}`,
    }),
    getSource: build.query<Source, number>({
      query: (id) => `/sources/${String(id)}`,
    }),
    askAboutDraft: build.mutation<MailAskResponse, MailAskRequest>({
      query: (body) => ({ url: '/mail/ask', method: 'POST', body }),
    }),
    sendFeedback: build.mutation<{ id: number }, FeedbackRequest>({
      query: (body) => ({ url: '/feedback', method: 'POST', body }),
    }),
  }),
});

export const {
  useAskMutation,
  useGetConversationQuery,
  useLazyGetSourceQuery,
  useAskAboutDraftMutation,
  useSendFeedbackMutation,
} = qaApi;
