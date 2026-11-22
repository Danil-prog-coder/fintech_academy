import { Link } from 'react-router';

import { useListAccountsQuery } from '@/entities/mailbox';
import { roleLabel, useGetProjectsQuery } from '@/entities/project';
import { getErrorMessage } from '@/shared/api';
import { routePaths } from '@/shared/config';
import { Button, EmptyState, Notice, Skeleton } from '@/shared/ui';
import { AppHeader } from '@/widgets/app-header';

import styles from './OverviewPage.module.css';

/** Главная: текущий проект на платформе, подключённые ящики и ссылки на разделы. */
export const OverviewPage = () => {
  const projects = useGetProjectsQuery(undefined);
  const current = projects.data?.projects.find((p) => p.id === projects.data?.current_project_id);
  const accounts = useListAccountsQuery(undefined);

  return (
    <div className={styles.page}>
      <AppHeader />
      <main className={styles.main}>
        <h1 className={styles.title}>Главная</h1>
        <div className={styles.grid}>
          <section className={styles.card} aria-label="Проект">
            <h2 className={styles.subtitle}>Проект</h2>
            {projects.isLoading ? <Skeleton height={80} /> : null}
            {projects.error ? (
              <Notice tone="danger">{getErrorMessage(projects.error)}</Notice>
            ) : null}
            {projects.data && !current ? (
              <EmptyState
                title="Проекта нет"
                text="Создайте проект или попросите владельца добавить вас — тогда можно задавать вопросы по его документации."
              />
            ) : null}
            {current ? (
              <p>
                <strong>{current.name}</strong> — вы {roleLabel[current.role]}. Вопросы из чата и
                «Спросить у ИИ» идут в документацию этого проекта.
              </p>
            ) : null}
            <div className={styles.actions}>
              <Link to={routePaths.projects}>
                <Button variant="secondary">Проекты</Button>
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
