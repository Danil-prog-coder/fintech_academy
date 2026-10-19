import { baseApi } from '@/shared/api';
import { delay } from '@/shared/lib/time';

import { type Source } from '../model/types';

const formatCheckDate = (date: Date) =>
  `${date.toLocaleDateString('ru-RU', { day: 'numeric', month: 'short', year: 'numeric' }).replace(' г.', '')}, ${date.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })}`;

let mockSources: Source[] = [
  {
    id: 'src-mail',
    name: 'Корпоративная почта',
    kind: 'mail',
    typeLabel: 'Почта',
    allowedData: 'Метаданные писем (отправитель, получатель, дата, тема, вложения, размер).',
    status: 'working',
    lastCheckLabel: '17 окт. 2026, 10:24',
    lastCheckResult: 'Успешно',
    aiActions: 892,
  },
  {
    id: 'src-docs',
    name: 'Общие документы',
    kind: 'documents',
    typeLabel: 'Документы',
    allowedData: 'Названия, типы, дата изменения, автор, доступные разделы.',
    status: 'working',
    lastCheckLabel: '17 окт. 2026, 09:17',
    lastCheckResult: 'Успешно',
    aiActions: 236,
  },
  {
    id: 'src-work-docs',
    name: 'Рабочие документы',
    kind: 'documents',
    typeLabel: 'Документы',
    allowedData: 'Названия, типы, дата изменения, доступные разделы проекта.',
    status: 'working',
    lastCheckLabel: '17 окт. 2026, 08:02',
    lastCheckResult: 'Успешно',
    aiActions: 76,
  },
  {
    id: 'src-extra',
    name: 'Дополнительный источник',
    kind: 'other',
    typeLabel: 'Другое',
    allowedData: 'Метаданные по доступным объектам (названия, типы, дата изменения).',
    status: 'attention',
    lastCheckLabel: '16 окт. 2026, 16:41',
    lastCheckResult: 'Не удалось подключиться',
    aiActions: 0,
  },
];

export const sourceApi = baseApi.injectEndpoints({
  endpoints: (build) => ({
    getSources: build.query<Source[], undefined>({
      queryFn: async () => {
        await delay(250);
        return { data: mockSources };
      },
      providesTags: ['Source'],
    }),
    /** Проверка подключения. Дополнительный источник в демо остаётся недоступным. */
    checkSource: build.mutation<Source, string>({
      queryFn: async (id) => {
        await delay(900);
        const source = mockSources.find((item) => item.id === id);
        if (!source) {
          return { error: { status: 404, data: 'Источник не найден' } };
        }
        const updated: Source = {
          ...source,
          lastCheckLabel: formatCheckDate(new Date()),
          lastCheckResult: source.kind === 'other' ? 'Не удалось подключиться' : 'Успешно',
        };
        mockSources = mockSources.map((item) => (item.id === id ? updated : item));
        return { data: updated };
      },
      invalidatesTags: ['Source'],
    }),
  }),
});

export const { useGetSourcesQuery, useCheckSourceMutation } = sourceApi;
