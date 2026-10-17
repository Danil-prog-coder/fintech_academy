import { CircleQuestionMark, LayoutDashboard, Mail } from 'lucide-react';
import { useNavigate } from 'react-router';

import { currentUser, UserChip } from '@/entities/user';
import { routePaths } from '@/shared/config';
import { showToast } from '@/shared/lib/toast';
import { DropdownMenu, IconButton, Logo } from '@/shared/ui';

import styles from './ConnectHeader.module.css';

export const ConnectHeader = () => {
  const navigate = useNavigate();

  return (
    <header className={styles.header}>
      <Logo size="lg" />
      <div className={styles.right}>
        <IconButton
          label="Помощь"
          icon={<CircleQuestionMark size={26} strokeWidth={1.8} />}
          onClick={() => {
            showToast(
              'Подключение выполняется через корпоративную учётную запись. Пароли не сохраняются.',
            );
          }}
        />
        <DropdownMenu
          label="Меню пользователя"
          trigger={<UserChip user={currentUser} />}
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
              id: 'admin',
              label: 'Кабинет администратора',
              icon: <LayoutDashboard size={18} />,
              onSelect: () => {
                void navigate(routePaths.admin);
              },
            },
          ]}
        />
      </div>
    </header>
  );
};
