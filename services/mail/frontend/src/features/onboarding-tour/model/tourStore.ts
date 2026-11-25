/**
 * Состояние тура: открыт ли он и пройден ли этим пользователем в этом браузере.
 *
 * Отметка «пройден» хранится в localStorage по id пользователя: у общего демо-аккаунта
 * каждый гость (на своём компьютере) увидит тур один раз. Если хранилище недоступно
 * (приватный режим), тур просто покажется снова — это не ошибка.
 */
type Listener = () => void;

const listeners = new Set<Listener>();
let open = false;

const doneKey = (userId: number) => `fa.tour.done.${String(userId)}`;

const emit = () => {
  listeners.forEach((listener) => {
    listener();
  });
};

export const isTourDone = (userId: number): boolean => {
  try {
    return localStorage.getItem(doneKey(userId)) === '1';
  } catch {
    return false;
  }
};

export const markTourDone = (userId: number): void => {
  try {
    localStorage.setItem(doneKey(userId), '1');
  } catch {
    // нет доступа к хранилищу — тур покажется при следующем входе
  }
};

export const isTourOpen = () => open;

export const startTour = (): void => {
  open = true;
  emit();
};

export const closeTour = (): void => {
  open = false;
  emit();
};

export const subscribeTour = (listener: Listener): (() => void) => {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
};
