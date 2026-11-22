export type ToastTone = 'neutral' | 'success' | 'warning' | 'danger';

export interface ToastMessage {
  id: number;
  text: string;
  tone: ToastTone;
}

type Listener = (toasts: ToastMessage[]) => void;

let toasts: ToastMessage[] = [];
let nextId = 1;
const listeners = new Set<Listener>();

const emit = () => {
  listeners.forEach((listener) => {
    listener(toasts);
  });
};

export const dismissToast = (id: number) => {
  toasts = toasts.filter((toast) => toast.id !== id);
  emit();
};

/** Показывает короткое уведомление. Не зависит от Redux — это инфраструктура UI. */
export const showToast = (text: string, tone: ToastTone = 'neutral') => {
  const id = nextId++;
  toasts = [...toasts, { id, text, tone }];
  emit();
  setTimeout(() => {
    dismissToast(id);
  }, 3500);
};

export const subscribeToasts = (listener: Listener) => {
  listeners.add(listener);
  listener(toasts);
  return () => {
    listeners.delete(listener);
  };
};
