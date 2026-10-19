import { X } from 'lucide-react';
import { type InputHTMLAttributes, type ReactNode, type Ref } from 'react';

import { cx } from '@/shared/lib/cx';

import styles from './TextField.module.css';

interface TextFieldProps extends Omit<InputHTMLAttributes<HTMLInputElement>, 'onChange' | 'size'> {
  value: string;
  onChange: (value: string) => void;
  label: string;
  icon?: ReactNode;
  trailing?: ReactNode;
  clearable?: boolean;
  size?: 'md' | 'lg';
  highlighted?: boolean;
  ref?: Ref<HTMLInputElement>;
}

export const TextField = ({
  value,
  onChange,
  label,
  icon,
  trailing,
  clearable = false,
  size = 'md',
  highlighted = false,
  className,
  ref,
  ...rest
}: TextFieldProps) => (
  <label className={cx(styles.field, styles[size], highlighted && styles.highlighted, className)}>
    <span className={styles.visuallyHidden}>{label}</span>
    {icon ? <span className={styles.icon}>{icon}</span> : null}
    <input
      ref={ref}
      className={styles.input}
      value={value}
      onChange={(event) => {
        onChange(event.target.value);
      }}
      {...rest}
    />
    {clearable && value ? (
      <button
        type="button"
        className={styles.clear}
        aria-label="Очистить"
        onClick={() => {
          onChange('');
        }}
      >
        <X size={18} />
      </button>
    ) : null}
    {trailing}
  </label>
);
