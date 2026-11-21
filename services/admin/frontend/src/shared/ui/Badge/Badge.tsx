import { type ReactNode } from 'react';

import { cx } from '@/shared/lib/cx';

import styles from './Badge.module.css';

export type BadgeTone = 'neutral' | 'success' | 'warning' | 'danger' | 'info' | 'accent';

interface BadgeProps {
  tone?: BadgeTone;
  dot?: boolean;
  icon?: ReactNode;
  plain?: boolean;
  children: ReactNode;
}

export const Badge = ({
  tone = 'neutral',
  dot = false,
  icon,
  plain = false,
  children,
}: BadgeProps) => (
  <span className={cx(styles.badge, styles[tone], plain && styles.plain)}>
    {dot ? <span className={styles.dot} aria-hidden="true" /> : null}
    {icon ? <span className={styles.icon}>{icon}</span> : null}
    {children}
  </span>
);
