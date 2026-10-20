import { LogOut } from 'lucide-react';
import { NavLink } from 'react-router';

import { useGetMeQuery, useLogout } from '@/entities/session';
import { routePaths } from '@/shared/config';
import { cx } from '@/shared/lib/cx';
import { Avatar, DropdownMenu, Logo } from '@/shared/ui';

import styles from './AppHeader.module.css';

const links = [
  { to: routePaths.root, label: 'Главная', end: true },
  { to: routePaths.mail, label: 'Почта', end: false },
  { to: routePaths.repo, label: 'Репозиторий', end: false },
  { to: routePaths.chat, label: 'Чат', end: false },
];

/** Шапка разделов, кроме самой почты: навигация и меню пользователя. */
export const AppHeader = () => {
  const { data: me } = useGetMeQuery(undefined);
  const logout = useLogout();
  const email = me?.email ?? '';

  return (
    <header className={styles.header}>
      <Logo caption="Почта" />
      <nav className={styles.nav} aria-label="Разделы">
        {links.map(({ to, label, end }) => (
          <NavLink
            key={to}
            to={to}
            end={end}
            className={({ isActive }) => cx(styles.link, isActive && styles.active)}
          >
            {label}
          </NavLink>
        ))}
      </nav>
      <DropdownMenu
        label="Меню пользователя"
        trigger={
          <span className={styles.user}>
            <Avatar initials={(email.slice(0, 2) || '?').toUpperCase()} size="md" />
            <span className={styles.email}>{email}</span>
          </span>
        }
        items={[{ id: 'logout', label: 'Выйти', icon: <LogOut size={18} />, onSelect: logout }]}
      />
    </header>
  );
};
