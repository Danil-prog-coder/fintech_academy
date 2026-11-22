import { ArrowLeftRight, LogOut } from 'lucide-react';
import { useNavigate } from 'react-router';

import { useGetMeQuery, useLogout } from '@/entities/session';
import { routePaths } from '@/shared/config';
import { Avatar, DropdownMenu, type DropdownMenuItem } from '@/shared/ui';

import styles from './AccountMenu.module.css';

/** Меню аккаунта в шапке, как в почте: аватар с логином, смена проекта и выход. */
export const AccountMenu = ({ canSwitchProject = true }: { canSwitchProject?: boolean }) => {
  const { data: me } = useGetMeQuery(undefined);
  const logout = useLogout();
  const navigate = useNavigate();
  const login = me?.login ?? '';
  const items: DropdownMenuItem[] = [
    ...(canSwitchProject
      ? [
          {
            id: 'projects',
            label: 'Сменить проект',
            icon: <ArrowLeftRight size={18} />,
            onSelect: () => void navigate(routePaths.projects),
          },
        ]
      : []),
    { id: 'logout', label: 'Выйти', icon: <LogOut size={18} />, onSelect: () => void logout() },
  ];
  return (
    <DropdownMenu
      label="Меню аккаунта"
      trigger={
        <span className={styles.user}>
          <Avatar initials={(login.slice(0, 2) || '?').toUpperCase()} size="md" />
          <span className={styles.login}>{login}</span>
        </span>
      }
      items={items}
    />
  );
};
