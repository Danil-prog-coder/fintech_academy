import { Eye, EyeOff, X } from 'lucide-react';
import { useState, type InputHTMLAttributes, type ReactNode, type Ref } from 'react';

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
  type,
  ...rest
}: TextFieldProps) => {
  // Поле пароля можно раскрыть, чтобы проверить, что введено.
  const [revealed, setRevealed] = useState(false);
  const isPassword = type === 'password';

  return (
    <label className={cx(styles.field, styles[size], highlighted && styles.highlighted, className)}>
      <span className={styles.visuallyHidden}>{label}</span>
      {icon ? <span className={styles.icon}>{icon}</span> : null}
      <input
        ref={ref}
        className={styles.input}
        type={isPassword && revealed ? 'text' : type}
        value={value}
        onChange={(event) => {
          onChange(event.target.value);
        }}
        {...rest}
      />
      {clearable && value ? (
        <button
          type="button"
          className={styles.action}
          aria-label="Очистить"
          onClick={() => {
            onChange('');
          }}
        >
          <X size={18} />
        </button>
      ) : null}
      {isPassword ? (
        <button
          type="button"
          className={styles.action}
          aria-label={revealed ? 'Скрыть пароль' : 'Показать пароль'}
          aria-pressed={revealed}
          title={revealed ? 'Скрыть пароль' : 'Показать пароль'}
          onClick={() => {
            setRevealed((shown) => !shown);
          }}
        >
          {revealed ? <EyeOff size={18} /> : <Eye size={18} />}
        </button>
      ) : null}
      {trailing}
    </label>
  );
};
