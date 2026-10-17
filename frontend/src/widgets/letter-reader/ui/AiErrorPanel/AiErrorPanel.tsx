import { Info, RefreshCw } from 'lucide-react';

import { Button, Notice } from '@/shared/ui';

import styles from './AiErrorPanel.module.css';

interface AiErrorPanelProps {
  title: string;
  onRetry: () => void;
  onContinueManually: () => void;
}

/** Ошибка AI: понятное сообщение, черновик не повреждён. */
export const AiErrorPanel = ({ title, onRetry, onContinueManually }: AiErrorPanelProps) => (
  <div className={styles.panel}>
    <Notice tone="danger" title={title} compact>
      Произошла ошибка при обработке. Ваш черновик сохранён.
    </Notice>
    <Button variant="primary" fullWidth icon={<RefreshCw size={18} />} onClick={onRetry}>
      Повторить
    </Button>
    <Button variant="soft" fullWidth onClick={onContinueManually}>
      Продолжить вручную
    </Button>
    <p className={styles.footnote}>
      <Info size={16} />
      Вы можете продолжить редактирование черновика — он сохранён.
    </p>
  </div>
);
