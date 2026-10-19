import { baseApi } from '@/shared/api';
import { delay } from '@/shared/lib/time';

import { type AuditEvent, type AuditEventStatus, type AuditEventType } from '../model/types';

const HOUR = 60 * 60 * 1000;

const event = (
  id: string,
  hoursAgo: number,
  type: AuditEventType,
  title: string,
  employee: string | null,
  source: string | null,
  status: AuditEventStatus = 'success',
): AuditEvent => ({
  id,
  at: new Date(Date.now() - hoursAgo * HOUR).toISOString(),
  type,
  title,
  employee,
  source,
  status,
});

/** События строятся относительно текущего времени, чтобы демо выглядело «живым». */
const createMockEvents = (): AuditEvent[] => [
  event('ev-1', 0.2, 'sync', 'Синхронизация источника', null, 'Почта'),
  event('ev-2', 1.3, 'employee', 'Добавлен сотрудник Иван Соколов', 'Иван Соколов', null),
  event(
    'ev-3',
    2.1,
    'transfer',
    'Попытка пересылки письма во внешний домен',
    'Мария К.',
    'Рабочая почта',
    'blocked',
  ),
  event('ev-4', 3.4, 'transfer', 'Скачивание вложения', 'Иван С.', 'Рабочая почта'),
  event('ev-5', 16.5, 'access', 'Обновлены настройки доступа', null, 'Документы'),
  event('ev-6', 18.4, 'source', 'Подключен источник', null, 'Общие документы'),
  event('ev-7', 19.2, 'ai', 'Использование AI-поиска', 'Ольга В.', 'Рабочая почта'),
  event(
    'ev-8',
    21.8,
    'transfer',
    'Попытка перехода по внешней ссылке',
    'Сергей Н.',
    'Рабочая почта',
    'blocked',
  ),
  event(
    'ev-9',
    44,
    'policy',
    'Изменение настроек политики хранения',
    'Алексей П.',
    'Системные настройки',
  ),
  event(
    'ev-10',
    52,
    'source',
    'Ошибка подключения источника',
    null,
    'Дополнительный источник',
    'failed',
  ),
  event('ev-11', 70, 'ai', 'Подготовка AI-черновика', 'Наталья С.', 'Рабочая почта'),
  event('ev-12', 96, 'employee', 'Отключён AI-помощник для сотрудника', 'Алексей И.', null),
];

let mockEvents = createMockEvents();

export const auditEventApi = baseApi.injectEndpoints({
  endpoints: (build) => ({
    getAuditEvents: build.query<AuditEvent[], undefined>({
      queryFn: async () => {
        await delay(250);
        return { data: mockEvents };
      },
      providesTags: ['AuditEvent'],
    }),
    logAuditEvent: build.mutation<undefined, Omit<AuditEvent, 'id' | 'at'>>({
      queryFn: async (payload) => {
        await delay(100);
        mockEvents = [
          { ...payload, id: `ev-${String(Date.now())}`, at: new Date().toISOString() },
          ...mockEvents,
        ];
        return { data: undefined };
      },
      invalidatesTags: ['AuditEvent'],
    }),
  }),
});

export const { useGetAuditEventsQuery, useLogAuditEventMutation } = auditEventApi;
