import { Check } from 'lucide-react';

import { cx } from '@/shared/lib/cx';
import { useAppSelector } from '@/shared/lib/store';
import { Logo, Spinner } from '@/shared/ui';

import styles from './PreparingProgress.module.css';
import { PREPARATION_STEPS } from '../../config/scenarios';
import { selectAiReply } from '../../model/aiReplySlice';

interface PreparingProgressProps {
  letterId: string;
}

export const PreparingProgress = ({ letterId }: PreparingProgressProps) => {
  const { step } = useAppSelector((state) => selectAiReply(state, letterId));

  return (
    <section className={styles.card} aria-live="polite">
      <header className={styles.header}>
        <div>
          <Logo size="sm" caption="Подготавливаем ответ" />
          <p className={styles.subtitle}>Анализируем запрос и подбираем релевантные материалы</p>
        </div>
        <span className={styles.status}>
          <Spinner size="md" label="Подготавливаем ответ" />
          Подготавливаем…
        </span>
      </header>
      <ol className={styles.steps}>
        {PREPARATION_STEPS.map((item, index) => {
          const state = index < step ? 'done' : index === step ? 'active' : 'pending';
          return (
            <li key={item.title} className={cx(styles.step, styles[state])}>
              <span className={styles.marker}>
                <span className={styles.dot}>
                  {state === 'done' ? <Check size={16} strokeWidth={3} /> : null}
                </span>
                {index < PREPARATION_STEPS.length - 1 ? <span className={styles.line} /> : null}
              </span>
              <span className={styles.title}>{item.title}</span>
              <span className={styles.description}>{item.description}</span>
            </li>
          );
        })}
      </ol>
    </section>
  );
};
