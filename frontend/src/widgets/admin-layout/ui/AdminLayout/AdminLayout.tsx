import {
  Bell,
  ChevronDown,
  Database,
  House,
  Mail,
  Plug,
  Settings,
  ShieldCheck,
  Users,
} from 'lucide-react';
import { type ReactNode } from 'react';
import { NavLink, useNavigate } from 'react-router';

import { adminUser, UserChip } from '@/entities/user';
import { routePaths } from '@/shared/config';
import { cx } from '@/shared/lib/cx';
import { showToast } from '@/shared/lib/toast';
import { Badge, DropdownMenu, IconButton, Logo } from '@/shared/ui';

import styles from './AdminLayout.module.css';

const navItems = [
  { to: routePaths.admin, label: 'Обзор', icon: House, end: true },
  { to: routePaths.adminEmployees, label: 'Сотрудники', icon: Users, end: false },
  { to: routePaths.adminSources, label: 'Источники', icon: Database, end: false },
  { to: routePaths.adminSecurity, label: 'Безопасность', icon: ShieldCheck, end: false },
  { to: routePaths.adminOrganization, label: 'Организация', icon: Settings, end: false },
];

interface AdminLayoutProps {
  title: string;
  subtitle: string;
  /** Дополнительный элемент справа от заголовка. */
  aside?: ReactNode;
  children: ReactNode;
}

/** Каркас кабинета администратора: навигация, шапка организации, заголовок страницы. */
export const AdminLayout = ({ title, subtitle, aside, children }: AdminLayoutProps) => {
  const navigate = useNavigate();

  return (
    <div className={styles.layout}>
      <aside className={styles.sidebar}>
        <div className={styles.logo}>
          <Logo size="lg" />
        </div>
        <nav className={styles.nav} aria-label="Разделы кабинета">
          {navItems.map(({ to, label, icon: Icon, end }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              className={({ isActive }) => cx(styles.navItem, isActive && styles.active)}
            >
              <Icon size={24} strokeWidth={1.8} />
              {label}
            </NavLink>
          ))}
        </nav>
      </aside>
      <div className={styles.content}>
        <header className={styles.header}>
          <DropdownMenu
            label="Выбор организации"
            align="left"
            trigger={
              <span className={styles.org}>
                Демо-компания <ChevronDown size={18} />
              </span>
            }
            items={[
              {
                id: 'demo',
                label: 'Демо-компания',
                onSelect: () => {
                  showToast('Вам доступна только одна организация');
                },
              },
            ]}
          />
          <Badge tone="neutral">Демонстрационные данные</Badge>
          <div className={styles.headerRight}>
            <IconButton
              label="Уведомления"
              icon={<Bell size={22} />}
              onClick={() => {
                showToast('Новых уведомлений нет');
              }}
            />
            <span className={styles.divider} />
            <DropdownMenu
              label="Меню администратора"
              trigger={<UserChip user={adminUser} tone="accent" />}
              items={[
                {
                  id: 'mail',
                  label: 'Перейти в почту',
                  icon: <Mail size={18} />,
                  onSelect: () => {
                    void navigate(routePaths.mail);
                  },
                },
                {
                  id: 'connect',
                  label: 'Подключения',
                  icon: <Plug size={18} />,
                  onSelect: () => {
                    void navigate(routePaths.connect);
                  },
                },
              ]}
            />
          </div>
        </header>
        <main className={styles.main}>
          <div className={styles.titleRow}>
            <div>
              <h1 className={styles.title}>{title}</h1>
              <p className={styles.subtitle}>{subtitle}</p>
            </div>
            {aside}
          </div>
          {children}
        </main>
      </div>
    </div>
  );
};
