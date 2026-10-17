export type AuditEventStatus = 'success' | 'blocked' | 'failed';

export type AuditEventType =
  'sync' | 'employee' | 'access' | 'source' | 'transfer' | 'ai' | 'policy';

/** Событие журнала. Содержимое писем в журнал не попадает. */
export interface AuditEvent {
  id: string;
  /** ISO-время события. */
  at: string;
  type: AuditEventType;
  title: string;
  employee: string | null;
  source: string | null;
  status: AuditEventStatus;
}

export const auditEventTypeLabels: Record<AuditEventType, string> = {
  sync: 'Синхронизация',
  employee: 'Сотрудники',
  access: 'Доступы',
  source: 'Источники',
  transfer: 'Передача данных',
  ai: 'AI-функции',
  policy: 'Политики',
};

export const auditEventStatusLabels: Record<AuditEventStatus, string> = {
  success: 'Успешно',
  blocked: 'Действие заблокировано',
  failed: 'Ошибка',
};
