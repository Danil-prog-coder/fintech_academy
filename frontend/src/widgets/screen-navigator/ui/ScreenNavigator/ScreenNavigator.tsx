import { LayoutGrid, X } from 'lucide-react';
import { useState } from 'react';
import { useNavigate } from 'react-router';

import { cx } from '@/shared/lib/cx';
import { useAppDispatch } from '@/shared/lib/store';
import { IconButton } from '@/shared/ui';

import styles from './ScreenNavigator.module.css';
import { screenGroups, type ScreenId } from '../../config/screens';
import { applyScreen } from '../../model/applyScreen';

/** Плавающий навигатор по 26 экранам макета — для демонстрации и приёмки. */
export const ScreenNavigator = () => {
  const dispatch = useAppDispatch();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const [current, setCurrent] = useState<ScreenId | null>(null);

  const go = async (id: ScreenId, path: string) => {
    setCurrent(id);
    setOpen(false);
    await dispatch(applyScreen(id));
    void navigate(path);
  };

  return (
    <div className={styles.root}>
      {open ? (
        <div className={styles.panel} role="dialog" aria-label="Экраны макета">
          <header className={styles.header}>
            <span className={styles.title}>Экраны макета</span>
            <IconButton
              size="sm"
              label="Закрыть"
              icon={<X size={18} />}
              onClick={() => {
                setOpen(false);
              }}
            />
          </header>
          <div className={styles.groups}>
            {screenGroups.map((group) => (
              <section key={group.title} className={styles.group}>
                <h3 className={styles.groupTitle}>{group.title}</h3>
                <ul className={styles.list}>
                  {group.screens.map((screen) => (
                    <li key={screen.id}>
                      <button
                        type="button"
                        className={cx(styles.item, current === screen.id && styles.current)}
                        onClick={() => {
                          void go(screen.id, screen.path);
                        }}
                      >
                        <span className={styles.id}>{screen.id}</span>
                        {screen.title}
                      </button>
                    </li>
                  ))}
                </ul>
              </section>
            ))}
          </div>
        </div>
      ) : null}
      <button
        type="button"
        className={styles.trigger}
        aria-expanded={open}
        onClick={() => {
          setOpen((value) => !value);
        }}
      >
        <LayoutGrid size={18} />
        {current ? `Экран ${current}` : 'Экраны'}
      </button>
    </div>
  );
};
