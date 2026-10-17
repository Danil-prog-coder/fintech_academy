import { CircleAlert, CircleCheck, Info, Link, Pencil } from 'lucide-react';

import { cx } from '@/shared/lib/cx';
import { showToast } from '@/shared/lib/toast';
import { Button, Notice } from '@/shared/ui';

import styles from './RequestsPanel.module.css';

interface RequestsPanelProps {
  onEditReply: () => void;
}

const requests = [
  {
    id: 'presentation',
    title: 'Прислать финальную презентацию',
    confirmed: true,
    status: 'Подтверждено',
    note: 'Презентация прикреплена к письму.',
  },
  {
    id: 'budget',
    title: 'Подтвердить сумму бюджета',
    confirmed: false,
    status: 'Нет подтверждения',
    note: 'В письме нет конкретной суммы бюджета. Уточните у ответственного.',
  },
];

/** Составное письмо: каждый запрос отражён в ответе или помечен как открытый. */
export const RequestsPanel = ({ onEditReply }: RequestsPanelProps) => {
  const confirmed = requests.filter((request) => request.confirmed).length;

  return (
    <div className={styles.panel}>
      <div className={styles.summary}>
        <p className={styles.summaryTitle}>Статус запросов в этом письме</p>
        <p className={styles.summaryCount}>
          {confirmed} из {requests.length} подтверждено
        </p>
      </div>
      <ol className={styles.list}>
        {requests.map((request, index) => (
          <li key={request.id} className={styles.item}>
            <span className={cx(styles.icon, request.confirmed ? styles.ok : styles.open)}>
              {request.confirmed ? <CircleCheck size={24} /> : <CircleAlert size={24} />}
            </span>
            <span>
              <span className={styles.itemTitle}>
                {index + 1}. {request.title}
              </span>
              <span className={cx(styles.status, request.confirmed ? styles.ok : styles.open)}>
                {request.status}
              </span>
              <span className={styles.note}>{request.note}</span>
            </span>
          </li>
        ))}
      </ol>
      <Notice tone="warning" title="Перед отправкой проверьте сумму бюджета" compact>
        Мы не нашли подтверждения согласованной суммы в доступных источниках.
      </Notice>
      <div className={styles.actions}>
        <Button
          icon={<Link size={16} />}
          onClick={() => {
            showToast('Открываем источник: письмо от 10 октября');
          }}
        >
          Проверить источник
        </Button>
        <Button icon={<Pencil size={16} />} onClick={onEditReply}>
          Исправить ответ
        </Button>
      </div>
      <p className={styles.footnote}>
        <Info size={16} />
        AI анализирует текст письма и вложения. Проверьте ключевую информацию перед отправкой.
      </p>
    </div>
  );
};
