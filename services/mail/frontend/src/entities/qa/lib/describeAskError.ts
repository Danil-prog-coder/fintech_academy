import { getErrorCode, getErrorMessage } from '@/shared/api';

export interface AskErrorInfo {
  message: string;
  /** Ошибку лечит выбор или создание проекта — показываем ссылку на страницу проектов. */
  needsProject: boolean;
  retryable: boolean;
}

/** Понятное объяснение ошибок вопросов (чат и «Спросить у ИИ»). */
export const describeAskError = (error: unknown): AskErrorInfo => {
  const code = getErrorCode(error);
  switch (code) {
    case 'no_project':
    case 'not_a_member':
      return {
        message: 'Создайте проект или попросите владельца добавить вас в проект.',
        needsProject: true,
        retryable: false,
      };
    case 'platform_not_configured':
      return {
        message: 'Почта не подключена к платформе: на сервере нет PLATFORM_API_KEY.',
        needsProject: false,
        retryable: false,
      };
    case 'rate_limited':
      return {
        message: 'Слишком много запросов. Подождите немного и повторите.',
        needsProject: false,
        retryable: true,
      };
    default:
      return {
        message: getErrorMessage(error, 'Не удалось получить ответ.'),
        needsProject: false,
        retryable: code === null || code.startsWith('platform_') || code.startsWith('llm_'),
      };
  }
};
