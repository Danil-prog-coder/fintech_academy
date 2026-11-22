import { baseApi } from '@/shared/api';

import {
  type Answer,
  type Escalation,
  type FeedbackRequest,
  type MailAskRequest,
  type MailAskResponse,
  type ReplyDraftRequest,
  type ReplyDraftResponse,
} from '../model/types';

export const qaApi = baseApi.injectEndpoints({
  endpoints: (build) => ({
    ask: build.mutation<Answer, { message: string; files?: File[] }>({
      query: ({ message, files }) => {
        if (!files?.length) {
          return { url: '/chat/ask', method: 'POST', body: { message } };
        }
        const body = new FormData();
        body.set('message', message);
        for (const file of files) {
          body.append('files', file);
        }
        return { url: '/chat/ask/attachments', method: 'POST', body };
      },
    }),
    transcribe: build.mutation<{ text: string }, Blob>({
      query: (audio) => {
        const body = new FormData();
        body.set('audio', audio, 'voice.wav');
        return { url: '/chat/transcribe', method: 'POST', body };
      },
    }),
    resetChat: build.mutation<undefined, undefined>({
      query: () => ({ url: '/chat/reset', method: 'POST' }),
    }),
    askAboutDraft: build.mutation<MailAskResponse, MailAskRequest>({
      query: (body) => ({ url: '/mail/ask', method: 'POST', body }),
    }),
    replyDraft: build.mutation<ReplyDraftResponse, ReplyDraftRequest>({
      query: (body) => ({ url: '/mail/reply-draft', method: 'POST', body }),
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
  useTranscribeMutation,
  useResetChatMutation,
  useAskAboutDraftMutation,
  useReplyDraftMutation,
  useSendFeedbackMutation,
  useContactSupportMutation,
  useGetPopularQuery,
} = qaApi;
