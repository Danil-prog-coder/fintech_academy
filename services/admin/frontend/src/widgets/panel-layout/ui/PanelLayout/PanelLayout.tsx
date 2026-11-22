import {
  BookOpen,
  ChartColumn,
  CircleHelp,
  LifeBuoy,
  Settings,
  Sparkles,
  Users,
} from 'lucide-react';
import { type ReactNode } from 'react';
import { NavLink } from 'react-router';

import { roleLabel, useGetMeQuery, type Role } from '@/entities/session';
import { AccountMenu } from '@/features/account-menu';
import { routePaths } from '@/shared/config';
import { cx } from '@/shared/lib/cx';
import { Logo } from '@/shared/ui';

import styles from './PanelLayout.module.css';

const links: { to: string; label: string; icon: ReactNode; roles: Role[] }[] = [
  {
    to: routePaths.root,
    label: 'Статистика',
    icon: <ChartColumn size={18} />,
    roles: ['owner', 'admin'],
  },
  {
    to: routePaths.documents,
    label: 'Документация',
    icon: <BookOpen size={18} />,
    roles: ['owner', 'admin'],
  },
  {
    to: routePaths.questions,
    label: 'Вопросы без ответа',
    icon: <CircleHelp size={18} />,
    roles: ['owner', 'admin'],
  },
  {
    to: routePaths.members,
    label: 'Участники',
    icon: <Users size={18} />,
    roles: ['owner', 'admin'],
  },
  {
    to: routePaths.faq,
    label: 'Частые вопросы',
    icon: <Sparkles size={18} />,
    roles: ['owner', 'admin'],
  },
  {
    to: routePaths.tickets,
    label: 'Обращения в ТП',
    icon: <LifeBuoy size={18} />,
    roles: ['owner', 'admin', 'support'],
  },
  { to: routePaths.settings, label: 'Настройки', icon: <Settings size={18} />, roles: ['owner'] },
];

/** Каркас страниц сайта: шапка с проектом и ролью, меню по роли. */
export const PanelLayout = ({ title, children }: { title: string; children: ReactNode }) => {
  const { data: me } = useGetMeQuery(undefined);

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <Logo caption="Панель проекта" />
        {me?.project && me.role ? (
          <span className={styles.project}>
            📁 {me.project.name} · {roleLabel[me.role]}
          </span>
        ) : (
          <span className={styles.project} />
        )}
        <AccountMenu />
      </header>
      <div className={styles.body}>
        <nav className={styles.nav} aria-label="Разделы">
          {links
            .filter((l) => me?.role && l.roles.includes(me.role))
            .map((l) => (
              <NavLink
                key={l.to}
                to={l.to}
                end={l.to === routePaths.root}
                className={({ isActive }) => cx(styles.link, isActive && styles.active)}
              >
                {l.icon}
                {l.label}
              </NavLink>
            ))}
        </nav>
        <main className={styles.main}>
          <h1 className={styles.title}>{title}</h1>
          {children}
        </main>
      </div>
    </div>
  );
};
