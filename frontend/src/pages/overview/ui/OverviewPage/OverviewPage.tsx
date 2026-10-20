import { Link } from 'react-router';

import { useListAccountsQuery } from '@/entities/mailbox';
import { RepoStatusCard, useGetRepoStatusQuery } from '@/entities/repo';
import { getErrorMessage } from '@/shared/api';
import { routePaths } from '@/shared/config';
import { Button, EmptyState, Notice, Skeleton } from '@/shared/ui';
import { AppHeader } from '@/widgets/app-header';

import styles from './OverviewPage.module.css';

/** Главная: статус репозитория, подключённые ящики и ссылки на разделы. */
export const OverviewPage = () => {
  const repo = useGetRepoStatusQuery(undefined);
  const accounts = useListAccountsQuery(undefined);

  return (
    <div className={styles.page}>
      <AppHeader />
      <main className={styles.main}>
        <h1 className={styles.title}>Главная</h1>
        <div className={styles.grid}>
          <section className={styles.card} aria-label="Репозиторий">
            <h2 className={styles.subtitle}>Репозиторий</h2>
            {repo.isLoading ? <Skeleton height={80} /> : null}
            {repo.error ? <Notice tone="danger">{getErrorMessage(repo.error)}</Notice> : null}
            {repo.data ? (
              repo.data.status === 'not_connected' ? (
                <EmptyState
                  title="Репозиторий не подключён"
                  text="Подключите его, чтобы задавать вопросы."
                />
              ) : (
                <RepoStatusCard info={repo.data} />
              )
            ) : null}
            <div className={styles.actions}>
              <Link to={routePaths.repo}>
                <Button variant="secondary">Управление репозиторием</Button>
              </Link>
              <Link to={routePaths.chat}>
                <Button variant="primary">Открыть чат</Button>
              </Link>
            </div>
          </section>

          <section className={styles.card} aria-label="Почтовые ящики">
            <h2 className={styles.subtitle}>Почтовые ящики</h2>
            {accounts.isLoading ? <Skeleton height={80} /> : null}
            {accounts.error ? (
              <Notice tone="danger">{getErrorMessage(accounts.error)}</Notice>
            ) : null}
            {accounts.data?.length === 0 ? (
              <EmptyState title="Ящиков нет" text="Подключите ящик по IMAP/SMTP." />
            ) : null}
            {accounts.data && accounts.data.length > 0 ? (
              <ul className={styles.accounts}>
                {accounts.data.map((account) => (
                  <li key={account.id} className={styles.account}>
                    <span className={styles.accountEmail}>{account.email}</span>
                    <span className={styles.accountHost}>{account.imap_host}</span>
                  </li>
                ))}
              </ul>
            ) : null}
            <div className={styles.actions}>
              <Link to={routePaths.mail}>
                <Button variant="primary">Открыть почту</Button>
              </Link>
              <Link to={routePaths.connect}>
                <Button variant="secondary">Подключить ящик</Button>
              </Link>
            </div>
          </section>
        </div>
      </main>
    </div>
  );
};
