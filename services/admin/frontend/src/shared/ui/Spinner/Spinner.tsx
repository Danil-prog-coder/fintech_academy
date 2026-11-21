import { cx } from '@/shared/lib/cx';

import styles from './Spinner.module.css';

interface SpinnerProps {
  size?: 'sm' | 'md' | 'lg';
  label?: string;
}

export const Spinner = ({ size = 'md', label = 'Загрузка' }: SpinnerProps) => (
  <span className={cx(styles.spinner, styles[size])} role="status" aria-label={label} />
);
