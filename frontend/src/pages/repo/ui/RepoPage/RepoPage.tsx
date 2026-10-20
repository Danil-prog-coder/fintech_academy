import {
  isRepoBusy,
  POLL_INTERVAL_MS,
  RepoStatusCard,
  useGetRepoStatusQuery,
} from '@/entities/repo';
import { ConnectRepoForm, DisconnectRepoButton } from '@/features/connect-repo';
import { getErrorMessage } from '@/shared/api';
import { Button, Notice, Skeleton, Spinner } from '@/shared/ui';
import { AppHeader } from '@/widgets/app-header';

import styles from './RepoPage.module.css';

/** Подключение репозитория и состояние индекса (опрос раз в 3 с, пока идёт индексация). */
export const RepoPage = () => {
  const { data, error, isLoading, refetch } = useGetRepoStatusQuery(undefined, {
    pollingInterval: POLL_INTERVAL_MS,
    skipPollingIfUnfocused: true,
  });
  const busy = isRepoBusy(data?.status);
  const connected = data !== undefined && data.status !== 'not_connected';
  // Повторную форму показываем, когда подключать нечего или нужен новый токен.
  const showForm = data !== undefined && (!connected || data.status === 'reauth_required');

  return (
    <div className={styles.page}>
      <AppHeader />
      <main className={styles.main}>
        <h1 className={styles.title}>Репозиторий</h1>
        {isLoading ? <Skeleton height={120} /> : null}
        {error && !data ? (
          <Notice
            tone="danger"
            title="Не удалось получить статус"
            action={<Button onClick={() => void refetch()}>Повторить</Button>}
          >
            {getErrorMessage(error)}
          </Notice>
        ) : null}
        {data && connected ? (
          <section className={styles.card} aria-label="Состояние репозитория">
            <RepoStatusCard info={data} />
            {busy ? (
              <p className={styles.busy}>
                <Spinner size="sm" label="Индексация" /> Статус обновляется автоматически.
              </p>
            ) : null}
            <div>
              <DisconnectRepoButton />
            </div>
          </section>
        ) : null}
        {showForm ? (
          <section className={styles.card} aria-label="Подключение репозитория">
            <h2 className={styles.subtitle}>
              {connected ? 'Обновите токен доступа' : 'Подключите репозиторий GitHub'}
            </h2>
            <ConnectRepoForm current={data} />
          </section>
        ) : null}
      </main>
    </div>
  );
};
