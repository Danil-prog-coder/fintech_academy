import { type ButtonHTMLAttributes, type ReactNode } from 'react';

import { cx } from '@/shared/lib/cx';

import styles from './IconButton.module.css';

interface IconButtonProps extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, 'children'> {
  label: string;
  icon: ReactNode;
  size?: 'sm' | 'md';
  variant?: 'ghost' | 'outline';
  active?: boolean;
}

export const IconButton = ({
  label,
  icon,
  size = 'md',
  variant = 'ghost',
  active = false,
  className,
  type = 'button',
  ...rest
}: IconButtonProps) => (
  <button
    type={type}
    aria-label={label}
    title={label}
    className={cx(
      styles.iconButton,
      styles[size],
      styles[variant],
      active && styles.active,
      className,
    )}
    {...rest}
  >
    {icon}
  </button>
);
