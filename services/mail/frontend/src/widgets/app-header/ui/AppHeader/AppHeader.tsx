import { Bell, LogOut } from 'lucide-react';
import { NavLink } from 'react-router';

import { useGetNotificationsQuery, useMarkReadMutation } from '@/entities/notification';
import { useGetProjectsQuery } from '@/entities/project';
import { useGetMeQuery, useLogout } from '@/entities/session';
import { routePaths } from '@/shared/config';
import { cx } from '@/shared/lib/cx';
import { Avatar, DropdownMenu, Logo } from '@/shared/ui';

import styles from './AppHeader.module.css';

const links = [
  { to: routePaths.root, label: 'Главная', end: true },
  { to: routePaths.mail, label: 'Почта', end: false },
  { to: routePaths.projects, label: 'Проекты', end: false },
  { to: routePaths.chat, label: 'Чат', end: false },
];

/** Шапка разделов, кроме самой почты: навигация и меню пользователя. */
export const AppHeader = () => {
  const { data: me } = useGetMeQuery(undefined);
  const logout = useLogout();
  const email = me?.email ?? '';
  const { data: projects } = useGetProjectsQuery(undefined);
  const current = projects?.projects.find((p) => p.id === projects.current_project_id);
  // ответы админов и поддержки приходят уведомлениями: опрашиваем раз в 15 секунд
  const { data: notes } = useGetNotificationsQuery(undefined, {
    pollingInterval: 15000,
    skipPollingIfUnfocused: true,
  });
  const [markRead] = useMarkReadMutation();
  const unread = notes?.notifications.filter((n) => !n.read) ?? [];

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
      {current ? <span className={styles.project}>📁 {current.name}</span> : null}
      <DropdownMenu
        label="Уведомления"
        trigger={
          <span className={styles.user}>
            <Bell size={18} />
            {unread.length > 0 ? <span className={styles.badge}>{unread.length}</span> : null}
          </span>
        }
        items={
          (notes?.notifications.length ?? 0) === 0
            ? [{ id: 'empty', label: 'Уведомлений нет', onSelect: () => undefined }]
            : [
                ...(notes?.notifications.slice(0, 8).map((n) => ({
                  id: String(n.id),
                  label: `${n.read ? '' : '● '}${n.title}${n.text ? ` — ${n.text.slice(0, 140)}` : ''}`,
                  onSelect: () => void markRead({ ids: [n.id] }),
                })) ?? []),
                {
                  id: 'all',
                  label: 'Отметить все прочитанными',
                  onSelect: () => void markRead({}),
                },
              ]
        }
      />
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
