import { baseApi } from '@/shared/api';

export type QuestionStatus = 'pending' | 'answered' | 'dismissed';

export interface Question {
  id: number;
  external_id: string;
  text: string;
  origin: 'no_answer' | 'dislike';
  status: QuestionStatus;
  answer: string | null;
  saved_to_kb: boolean;
  created_at: string;
  answered_at: string | null;
}

export const questionApi = baseApi.injectEndpoints({
  endpoints: (build) => ({
    getQuestions: build.query<{ questions: Question[]; total: number }, QuestionStatus>({
      query: (status) => `/questions?status=${status}`,
      providesTags: ['Questions'],
    }),
    answerQuestion: build.mutation<
      Question,
      { id: number; text: string; save_to_kb: boolean; section?: string }
    >({
      query: ({ id, ...body }) => ({
        url: `/questions/${String(id)}/answer`,
        method: 'POST',
        body,
      }),
      invalidatesTags: ['Questions', 'Stats', 'Docs'],
    }),
    dismissQuestion: build.mutation<Question, number>({
      query: (id) => ({ url: `/questions/${String(id)}/dismiss`, method: 'POST' }),
      invalidatesTags: ['Questions', 'Stats'],
    }),
  }),
});

export const { useGetQuestionsQuery, useAnswerQuestionMutation, useDismissQuestionMutation } =
  questionApi;
