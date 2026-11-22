import { ChevronDown } from 'lucide-react';

import { cx } from '@/shared/lib/cx';

import styles from './Select.module.css';

export interface SelectOption<T extends string> {
  value: T;
  label: string;
}

interface SelectProps<T extends string> {
  value: T;
  options: readonly SelectOption<T>[];
  onChange: (value: T) => void;
  label: string;
  size?: 'sm' | 'md';
  disabled?: boolean;
  fullWidth?: boolean;
}

export const Select = <T extends string>({
  value,
  options,
  onChange,
  label,
  size = 'md',
  disabled = false,
  fullWidth = false,
}: SelectProps<T>) => (
  <span className={cx(styles.wrapper, fullWidth && styles.fullWidth)}>
    <select
      aria-label={label}
      className={cx(styles.select, styles[size])}
      value={value}
      disabled={disabled}
      onChange={(event) => {
        const next = options.find((option) => option.value === event.target.value);
        if (next) {
          onChange(next.value);
        }
      }}
    >
      {options.map((option) => (
        <option key={option.value} value={option.value}>
          {option.label}
        </option>
      ))}
    </select>
    <ChevronDown className={styles.chevron} size={18} aria-hidden="true" />
  </span>
);
