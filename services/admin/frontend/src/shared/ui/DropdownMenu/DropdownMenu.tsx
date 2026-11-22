import { type ReactNode, useEffect, useRef, useState } from 'react';

import { cx } from '@/shared/lib/cx';

import styles from './DropdownMenu.module.css';

export interface DropdownMenuItem {
  id: string;
  label: string;
  icon?: ReactNode;
  danger?: boolean;
  onSelect: () => void;
}

interface DropdownMenuProps {
  /** Содержимое кнопки-триггера. */
  trigger: ReactNode;
  label: string;
  items: readonly DropdownMenuItem[];
  align?: 'left' | 'right';
  triggerClassName?: string;
}

export const DropdownMenu = ({
  trigger,
  label,
  items,
  align = 'right',
  triggerClassName,
}: DropdownMenuProps) => {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) {
      return undefined;
    }
    const handlePointerDown = (event: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(event.target as Node)) {
        setOpen(false);
      }
    };
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setOpen(false);
      }
    };
    document.addEventListener('mousedown', handlePointerDown);
    document.addEventListener('keydown', handleKeyDown);
    return () => {
      document.removeEventListener('mousedown', handlePointerDown);
      document.removeEventListener('keydown', handleKeyDown);
    };
  }, [open]);

  return (
    <div ref={rootRef} className={styles.root}>
      <button
        type="button"
        className={cx(styles.trigger, triggerClassName)}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={label}
        onClick={() => {
          setOpen((value) => !value);
        }}
      >
        {trigger}
      </button>
      {open ? (
        <div className={cx(styles.menu, styles[align])} role="menu">
          {items.map((item) => (
            <button
              key={item.id}
              type="button"
              role="menuitem"
              className={cx(styles.item, item.danger && styles.danger)}
              onClick={() => {
                setOpen(false);
                item.onSelect();
              }}
            >
              {item.icon ? <span className={styles.icon}>{item.icon}</span> : null}
              {item.label}
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
};
