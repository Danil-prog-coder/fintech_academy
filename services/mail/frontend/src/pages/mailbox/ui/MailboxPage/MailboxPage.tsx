import { Navigate } from 'react-router';

import { useActiveAccount } from '@/entities/mailbox';
import { ComposeModal } from '@/features/compose-message';
import { getErrorMessage } from '@/shared/api';
import { routePaths } from '@/shared/config';
import { Button, Notice, Spinner } from '@/shared/ui';
import { MailboxHeader } from '@/widgets/mailbox-header';
import { MailboxSidebar } from '@/widgets/mailbox-sidebar';
import { MessageList } from '@/widgets/message-list';
import { MessageReader } from '@/widgets/message-reader';

import styles from './MailboxPage.module.css';

/** Почтовый клиент: папки, список писем и чтение выбранного письма. */
export const MailboxPage = () => {
  const { account, accounts, isLoading, isError, refetch } = useActiveAccount();

  if (isLoading) {
    return (
      <div className={styles.center}>
        <Spinner size="lg" label="Загрузка ящиков" />
      </div>
    );
  }
  if (isError) {
    return (
      <div className={styles.center}>
        <Notice
          tone="danger"
          title="Не удалось загрузить список ящиков"
          action={<Button onClick={() => void refetch()}>Повторить</Button>}
        >
          {getErrorMessage(undefined, 'Проверьте соединение с сервером.')}
        </Notice>
      </div>
    );
  }
  if (accounts.length === 0) {
    return <Navigate to={routePaths.connect} replace />;
  }

  return (
    <div className={styles.page}>
      <div className={styles.sidebar}>
        <MailboxSidebar />
      </div>
      <div className={styles.header}>
        <MailboxHeader />
      </div>
      <div className={styles.list}>
        <MessageList />
      </div>
      <main className={styles.reader}>
        <MessageReader />
      </main>
      <ComposeModal accountId={account?.id ?? null} />
    </div>
  );
};
