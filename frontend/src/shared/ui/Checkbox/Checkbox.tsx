import { Check } from 'lucide-react';

import { cx } from '@/shared/lib/cx';

import styles from './Checkbox.module.css';

interface CheckboxProps {
  checked: boolean;
  onChange: (checked: boolean) => void;
  label: string;
  description?: string;
  hideLabel?: boolean;
}

export const Checkbox = ({
  checked,
  onChange,
  label,
  description,
  hideLabel = false,
}: CheckboxProps) => (
  <label className={styles.checkbox}>
    <input
      type="checkbox"
      className={styles.input}
      checked={checked}
      aria-label={hideLabel ? label : undefined}
      onChange={(event) => {
        onChange(event.target.checked);
      }}
    />
    <span className={cx(styles.box, checked && styles.checked)} aria-hidden="true">
      {checked ? <Check size={14} strokeWidth={3} /> : null}
    </span>
    {hideLabel ? null : (
      <span className={styles.text}>
        <span className={styles.label}>{label}</span>
        {description ? <span className={styles.description}>{description}</span> : null}
      </span>
    )}
  </label>
);
