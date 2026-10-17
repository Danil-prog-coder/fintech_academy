import { cx } from '@/shared/lib/cx';

import styles from './Toggle.module.css';

interface ToggleProps {
  checked: boolean;
  onChange: (checked: boolean) => void;
  label: string;
  showLabel?: boolean;
  disabled?: boolean;
}

export const Toggle = ({
  checked,
  onChange,
  label,
  showLabel = false,
  disabled = false,
}: ToggleProps) => (
  <button
    type="button"
    role="switch"
    aria-checked={checked}
    aria-label={showLabel ? undefined : label}
    disabled={disabled}
    className={styles.toggle}
    onClick={() => {
      onChange(!checked);
    }}
  >
    <span className={cx(styles.track, checked && styles.checked)}>
      <span className={styles.thumb} />
    </span>
    {showLabel ? <span className={styles.label}>{label}</span> : null}
  </button>
);
