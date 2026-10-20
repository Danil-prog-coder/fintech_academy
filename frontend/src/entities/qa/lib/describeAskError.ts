import { getErrorCode, getErrorMessage } from '@/shared/api';

export interface AskErrorInfo {
  message: string;
  /** Ошибку лечит подключение репозитория — показываем ссылку на его страницу. */
  needsRepo: boolean;
  retryable: boolean;
}

/** Понятное объяснение ошибок вопросов к ассистенту (чат и «Спросить у ИИ»). */
export const describeAskError = (error: unknown): AskErrorInfo => {
  const code = getErrorCode(error);
  switch (code) {
    case 'repo_not_connected':
      return { message: 'Сначала подключите репозиторий.', needsRepo: true, retryable: false };
    case 'index_not_ready':
      return {
        message: 'Индекс репозитория ещё строится. Дождитесь статуса «Готов к вопросам».',
        needsRepo: true,
        retryable: true,
      };
    case 'llm_not_configured':
      return {
        message:
          'Языковая модель не настроена: на сервере нет ключей GigaChat. Добавьте ключи в back-end/.env и перезапустите сервер.',
        needsRepo: false,
        retryable: false,
      };
    case 'rate_limited':
      return {
        message: 'Слишком много запросов. Подождите немного и повторите.',
        needsRepo: false,
        retryable: true,
      };
    default:
      return {
        message: getErrorMessage(error, 'Не удалось получить ответ.'),
        needsRepo: false,
        retryable: code === null || code.startsWith('llm_'),
      };
  }
};
