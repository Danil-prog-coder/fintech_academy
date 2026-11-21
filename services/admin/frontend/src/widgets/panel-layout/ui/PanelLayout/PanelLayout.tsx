import {
  BookOpen,
  ChartColumn,
  CircleHelp,
  LifeBuoy,
  LogOut,
  Settings,
  Sparkles,
  Users,
} from 'lucide-react';
import { type ReactNode } from 'react';
import { NavLink, useNavigate } from 'react-router';

import {
  roleLabel,
  sessionApi,
  useGetMeQuery,
  useLogoutMutation,
  type Role,
} from '@/entities/session';
import { routePaths } from '@/shared/config';
import { cx } from '@/shared/lib/cx';
import { useAppDispatch } from '@/shared/lib/store';
import { Button, Logo } from '@/shared/ui';

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
  const [logout] = useLogoutMutation();
  const navigate = useNavigate();
  const dispatch = useAppDispatch();

  const exit = async () => {
    try {
      await logout(undefined).unwrap();
    } finally {
      dispatch(sessionApi.util.resetApiState());
      void navigate(routePaths.login, { replace: true });
    }
  };

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <Logo caption="Панель проекта" />
        {me ? (
          <span className={styles.project}>
            📁 {me.project.name} · {roleLabel[me.role]} · {me.login}
          </span>
        ) : null}
        <Button size="sm" variant="ghost" icon={<LogOut size={16} />} onClick={() => void exit()}>
          Выйти
        </Button>
      </header>
      <div className={styles.body}>
        <nav className={styles.nav} aria-label="Разделы">
          {links
            .filter((l) => me && l.roles.includes(me.role))
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
