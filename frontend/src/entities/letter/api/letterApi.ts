import { baseApi } from '@/shared/api';
import { delay } from '@/shared/lib/time';

import { mockInbox } from './mockLetters';
import { type Letter, type LetterFolder } from '../model/types';

/** Письма читаются из почтового клиента; здесь — демонстрационная реализация. */
export const letterApi = baseApi.injectEndpoints({
  endpoints: (build) => ({
    getLetters: build.query<Letter[], LetterFolder>({
      queryFn: async (folder) => {
        await delay(200);
        return { data: folder === 'inbox' ? mockInbox : [] };
      },
      providesTags: ['Letter'],
    }),
    getLetter: build.query<Letter, string>({
      queryFn: async (id) => {
        await delay(100);
        const letter = mockInbox.find((item) => item.id === id);
        return letter ? { data: letter } : { error: { status: 404, data: 'Письмо не найдено' } };
      },
      providesTags: ['Letter'],
    }),
  }),
});

export const { useGetLettersQuery, useGetLetterQuery } = letterApi;
