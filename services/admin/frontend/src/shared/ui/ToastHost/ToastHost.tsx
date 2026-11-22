import { X } from 'lucide-react';
import { useEffect, useState } from 'react';

import { cx } from '@/shared/lib/cx';
import { dismissToast, subscribeToasts, type ToastMessage } from '@/shared/lib/toast';

import styles from './ToastHost.module.css';

export const ToastHost = () => {
  const [toasts, setToasts] = useState<ToastMessage[]>([]);

  useEffect(() => subscribeToasts(setToasts), []);

  return (
    <div className={styles.host} aria-live="polite">
      {toasts.map((toast) => (
        <div key={toast.id} className={cx(styles.toast, styles[toast.tone])}>
          <span className={styles.text}>{toast.text}</span>
          <button
            type="button"
            className={styles.close}
            aria-label="Скрыть уведомление"
            onClick={() => {
              dismissToast(toast.id);
            }}
          >
            <X size={16} />
          </button>
        </div>
      ))}
    </div>
  );
};
