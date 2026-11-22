import { type ButtonHTMLAttributes, type ReactNode } from 'react';

import { cx } from '@/shared/lib/cx';

import styles from './Button.module.css';

type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'soft' | 'danger' | 'link';
type ButtonSize = 'sm' | 'md' | 'lg';

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  icon?: ReactNode;
  iconAfter?: ReactNode;
  fullWidth?: boolean;
}

export const Button = ({
  variant = 'secondary',
  size = 'md',
  icon,
  iconAfter,
  fullWidth = false,
  className,
  children,
  type = 'button',
  ...rest
}: ButtonProps) => (
  <button
    type={type}
    className={cx(
      styles.button,
      styles[variant],
      styles[size],
      fullWidth && styles.fullWidth,
      className,
    )}
    {...rest}
  >
    {icon ? <span className={styles.icon}>{icon}</span> : null}
    {children}
    {iconAfter ? <span className={styles.icon}>{iconAfter}</span> : null}
  </button>
);
