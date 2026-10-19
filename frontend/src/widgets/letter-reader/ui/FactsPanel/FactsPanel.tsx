import { CircleAlert, CircleCheck, CircleQuestionMark, FileText } from 'lucide-react';

import { showToast } from '@/shared/lib/toast';
import { Button } from '@/shared/ui';

import styles from './FactsPanel.module.css';

interface FactsPanelProps {
  amount: string;
  onClarify: () => void;
}

/** Значимые факты ответа и их подтверждение источниками. */
export const FactsPanel = ({ amount, onClarify }: FactsPanelProps) => (
  <div className={styles.panel}>
    <h3 className={styles.heading}>Проверка фактов</h3>
    <div className={styles.fact}>
      <CircleCheck size={28} className={styles.ok} />
      <div className={styles.body}>
        <p className={styles.title}>Презентация согласована</p>
        <p className={styles.meta}>Подтверждено в письме</p>
        <button
          type="button"
          className={styles.link}
          onClick={() => {
            showToast('Открываем письмо руководителя от 10 октября');
          }}
        >
          <FileText size={16} />
          Письмо руководителя, 10 октября
        </button>
      </div>
      <Button
        size="sm"
        onClick={() => {
          showToast('Открываем источник с обычной проверкой доступа');
        }}
      >
        Открыть источник
      </Button>
    </div>
    <div className={styles.fact}>
      <CircleAlert size={28} className={styles.danger} />
      <div className={styles.body}>
        <p className={styles.title}>Бюджет {amount}</p>
        <p className={styles.unconfirmed}>
          Не подтверждено
          <span title="В доступных источниках нет согласования этой суммы">
            <CircleQuestionMark size={16} />
          </span>
        </p>
      </div>
      <div className={styles.actions}>
        <Button
          size="sm"
          onClick={() => {
            showToast('Найдено 2 источника с упоминанием суммы — согласование отсутствует');
          }}
        >
          Открыть источники
        </Button>
        <Button size="sm" variant="soft" onClick={onClarify}>
          Уточнить
        </Button>
      </div>
    </div>
  </div>
);
