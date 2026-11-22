const ACCESS_KEY = 'fa.access_token';
const REFRESH_KEY = 'fa.refresh_token';

export interface TokenPair {
  access_token: string;
  refresh_token: string;
}

type Listener = () => void;

const listeners = new Set<Listener>();

const read = (key: string): string | null => {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
};

const emit = () => {
  listeners.forEach((listener) => {
    listener();
  });
};

export const getAccessToken = () => read(ACCESS_KEY);

export const getRefreshToken = () => read(REFRESH_KEY);

export const hasTokens = () => getAccessToken() !== null;

export const saveTokens = (pair: TokenPair) => {
  try {
    localStorage.setItem(ACCESS_KEY, pair.access_token);
    localStorage.setItem(REFRESH_KEY, pair.refresh_token);
  } catch {
    // Хранилище недоступно (приватный режим): сессия не сохранится.
  }
  emit();
};

export const clearTokens = () => {
  try {
    localStorage.removeItem(ACCESS_KEY);
    localStorage.removeItem(REFRESH_KEY);
  } catch {
    // Нечего очищать.
  }
  emit();
};

/** Подписка на вход/выход — для useSyncExternalStore. */
export const subscribeTokens = (listener: Listener) => {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
};
