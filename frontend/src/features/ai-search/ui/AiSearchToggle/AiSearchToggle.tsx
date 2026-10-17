import { cx } from '@/shared/lib/cx';
import { useAppDispatch, useAppSelector } from '@/shared/lib/store';
import { Logo } from '@/shared/ui';

import styles from './AiSearchToggle.module.css';
import { searchPanelToggled, selectSearchOpen } from '../../model/aiSearchSlice';

interface AiSearchToggleProps {
  disabled?: boolean;
}

export const AiSearchToggle = ({ disabled = false }: AiSearchToggleProps) => {
  const dispatch = useAppDispatch();
  const open = useAppSelector(selectSearchOpen);

  return (
    <button
      type="button"
      className={cx(styles.toggle, open && styles.active)}
      aria-pressed={open}
      disabled={disabled}
      title={disabled ? 'AI-поиск недоступен: подключите рабочую почту' : 'AI-поиск'}
      onClick={() => {
        dispatch(searchPanelToggled());
      }}
    >
      <Logo size="sm" caption="AI-поиск" />
    </button>
  );
};
