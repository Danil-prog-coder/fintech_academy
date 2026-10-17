import { FileText } from 'lucide-react';
import { useEffect, useState } from 'react';

import { SEARCH_DURATION_MS } from '@/features/ai-search';
import { cx } from '@/shared/lib/cx';
import { Skeleton } from '@/shared/ui';

import styles from './SearchProgress.module.css';

const steps = [
  { title: 'Проверяем переписку', description: 'Ищем по письмам и вложениям…' },
  { title: 'Проверяем документы', description: 'Ищем по корпоративным файлам…' },
];

/** Ход выполнения AI-поиска: этапы и заглушки результатов. */
export const SearchProgress = () => {
  const [step, setStep] = useState(0);

  useEffect(() => {
    const timer = setTimeout(() => {
      setStep(1);
    }, SEARCH_DURATION_MS / 2);
    return () => {
      clearTimeout(timer);
    };
  }, []);

  return (
    <div className={styles.progress} aria-live="polite">
      <ol className={styles.steps}>
        {steps.map((item, index) => (
          <li
            key={item.title}
            className={cx(
              styles.step,
              index < step && styles.done,
              index === step && styles.active,
            )}
          >
            <span className={styles.marker} />
            <span className={styles.text}>
              <span className={styles.title}>{item.title}</span>
              <span className={styles.description}>{item.description}</span>
            </span>
          </li>
        ))}
      </ol>
      <div className={styles.placeholders} aria-hidden="true">
        {[0, 1, 2].map((item) => (
          <div key={item} className={styles.placeholder}>
            <span className={styles.fileIcon}>
              <FileText size={24} />
            </span>
            <span className={styles.lines}>
              <Skeleton width="55%" height={14} />
              <Skeleton width="85%" height={10} />
              <Skeleton width="45%" height={10} />
            </span>
          </div>
        ))}
      </div>
    </div>
  );
};
