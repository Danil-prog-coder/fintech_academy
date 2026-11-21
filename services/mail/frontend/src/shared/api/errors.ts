interface ApiErrorBody {
  code: string;
  message: string;
  retryable?: boolean;
}

const isApiErrorBody = (value: unknown): value is ApiErrorBody =>
  typeof value === 'object' &&
  value !== null &&
  typeof (value as { message?: unknown }).message === 'string';

/** Человекочитаемое сообщение из ответа backend `{code, message, retryable}` или сетевой ошибки. */
export const getErrorMessage = (error: unknown, fallback = 'Что-то пошло не так.'): string => {
  if (typeof error !== 'object' || error === null) {
    return fallback;
  }
  const { status, data } = error as { status?: unknown; data?: unknown };
  if (isApiErrorBody(data)) {
    return data.message;
  }
  if (status === 'FETCH_ERROR') {
    return 'Нет соединения с сервером.';
  }
  return fallback;
};

export const getErrorCode = (error: unknown): string | null => {
  if (typeof error !== 'object' || error === null) {
    return null;
  }
  const { data } = error as { data?: unknown };
  return isApiErrorBody(data) ? data.code : null;
};
