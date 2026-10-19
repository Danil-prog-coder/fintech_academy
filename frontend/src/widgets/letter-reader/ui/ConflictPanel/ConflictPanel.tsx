import { ChevronRight, FileText, Folder, Info, MessagesSquare } from 'lucide-react';

import { showToast } from '@/shared/lib/toast';
import { Button, Notice } from '@/shared/ui';

import styles from './ConflictPanel.module.css';

interface ConflictPanelProps {
  onClarify: () => void;
}

const variants = [
  { id: 'estimate', amount: '2 500 000 ₽', source: 'Смета', date: '12 октября' },
  { id: 'finance', amount: '2 800 000 ₽', source: 'Письмо финансового отдела', date: '14 октября' },
];

/** Противоречие: показываем оба значения и источники, без ложной отметки «проверено». */
export const ConflictPanel = ({ onClarify }: ConflictPanelProps) => (
  <div className={styles.panel}>
    <Notice tone="warning" title="Обнаружено противоречие" compact>
      Найдены разные значения суммы бюджета в источниках компании. Проверьте и уточните перед
      отправкой.
    </Notice>
    <p className={styles.heading}>Найденные варианты суммы</p>
    <ul className={styles.variants}>
      {variants.map((variant) => (
        <li key={variant.id}>
          <button
            type="button"
            className={styles.variant}
            onClick={() => {
              showToast(`Открываем источник: ${variant.source}, ${variant.date}`);
            }}
          >
            <FileText size={22} className={styles.fileIcon} />
            <span className={styles.variantText}>
              <span className={styles.amount}>{variant.amount}</span>
              <span className={styles.meta}>{variant.source}</span>
              <span className={styles.meta}>{variant.date}</span>
            </span>
            <ChevronRight size={18} />
          </button>
        </li>
      ))}
    </ul>
    <Button
      variant="soft"
      fullWidth
      icon={<Folder size={18} />}
      onClick={() => {
        showToast('Открываем оба источника для сверки');
      }}
    >
      Открыть источники
    </Button>
    <Button variant="primary" fullWidth icon={<MessagesSquare size={18} />} onClick={onClarify}>
      Уточнить сумму
    </Button>
    <p className={styles.footnote}>
      <Info size={16} />
      AI не выбирает значение автоматически. Проверьте источники и при необходимости уточните сумму
      в ответе.
    </p>
  </div>
);
