import { cx } from '@/shared/lib/cx';

import styles from './Avatar.module.css';

interface AvatarProps {
  initials: string;
  size?: 'sm' | 'md' | 'lg';
  tone?: 'neutral' | 'accent';
}

export const Avatar = ({ initials, size = 'md', tone = 'neutral' }: AvatarProps) => (
  <span className={cx(styles.avatar, styles[size], styles[tone])} aria-hidden="true">
    {initials}
  </span>
);
