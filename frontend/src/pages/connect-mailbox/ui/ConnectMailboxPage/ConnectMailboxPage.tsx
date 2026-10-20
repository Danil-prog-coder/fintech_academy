import { ArrowLeft } from 'lucide-react';
import { useNavigate } from 'react-router';

import { useActiveAccount } from '@/entities/mailbox';
import { ConnectMailboxForm } from '@/features/connect-mailbox';
import { routePaths } from '@/shared/config';
import { Button, Logo } from '@/shared/ui';

import styles from './ConnectMailboxPage.module.css';

export const ConnectMailboxPage = () => {
  const navigate = useNavigate();
  const { accounts } = useActiveAccount();
  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <Logo caption="Почта" />
        {accounts.length > 0 ? (
          <Button
            variant="ghost"
            icon={<ArrowLeft size={18} />}
            onClick={() => {
              void navigate(routePaths.mail);
            }}
          >
            К письмам
          </Button>
        ) : null}
      </header>
      <main className={styles.main}>
        <h1 className={styles.title}>Подключите почтовый ящик</h1>
        <ConnectMailboxForm
          onConnected={() => {
            void navigate(routePaths.mail, { replace: true });
          }}
        />
      </main>
    </div>
  );
};
