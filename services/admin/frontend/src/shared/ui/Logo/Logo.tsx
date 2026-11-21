import { cx } from '@/shared/lib/cx';

import styles from './Logo.module.css';

interface LogoProps {
  size?: 'sm' | 'md' | 'lg';
  withText?: boolean;
  caption?: string;
}

export const Logo = ({ size = 'md', withText = true, caption }: LogoProps) => (
  <span className={cx(styles.logo, styles[size])}>
    <svg className={styles.mark} viewBox="0 0 48 28" aria-hidden="true">
      <rect x="0" y="0" width="20" height="8" rx="2.5" fill="currentColor" />
      <rect x="0" y="20" width="20" height="8" rx="2.5" fill="currentColor" />
      <path d="M16 4h8l8 10-8 10h-8l8-10z" fill="currentColor" />
      <rect x="28" y="6" width="20" height="16" rx="4" fill="currentColor" />
      <rect x="33" y="12.5" width="10" height="3" rx="1.5" className={styles.accent} />
    </svg>
    {withText ? <span className={styles.text}>SOLUTIONS</span> : null}
    {caption ? <span className={styles.caption}>· {caption}</span> : null}
  </span>
);
