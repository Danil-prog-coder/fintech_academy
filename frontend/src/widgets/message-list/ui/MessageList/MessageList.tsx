import { ChevronLeft, ChevronRight, Inbox } from 'lucide-react';

import {
  messageSelected,
  MessageListItem,
  pageChanged,
  PAGE_SIZE,
  selectFolder,
  selectPage,
  selectQuery,
  selectSelectedUid,
  selectUnreadOnly,
  unreadOnlyChanged,
  useActiveAccount,
  useListFoldersQuery,
  useListMessagesQuery,
} from '@/entities/mailbox';
import { getErrorMessage } from '@/shared/api';
import { cx } from '@/shared/lib/cx';
import { useAppDispatch, useAppSelector } from '@/shared/lib/store';
import { Button, EmptyState, IconButton, Notice, Skeleton } from '@/shared/ui';

import styles from './MessageList.module.css';

const tabs = [
  { unread: false, label: 'Все письма' },
  { unread: true, label: 'Непрочитанные' },
];

export const MessageList = () => {
  const dispatch = useAppDispatch();
  const { account } = useActiveAccount();
  const folder = useAppSelector(selectFolder);
  const unreadOnly = useAppSelector(selectUnreadOnly);
  const query = useAppSelector(selectQuery);
  const page = useAppSelector(selectPage);
  const selectedUid = useAppSelector(selectSelectedUid);
  const accountId = account?.id ?? 0;

  const { data: folders } = useListFoldersQuery(accountId, { skip: !account });
  const { data, isLoading, isFetching, error, refetch } = useListMessagesQuery(
    { accountId, folder, unread: unreadOnly, query, limit: PAGE_SIZE, offset: page * PAGE_SIZE },
    { skip: !account },
  );

  const role = folders?.find((item) => item.path === folder)?.role;
  const showRecipient = role === 'sent' || role === 'drafts';
  const total = data?.total ?? 0;
  const first = total === 0 ? 0 : page * PAGE_SIZE + 1;
  const last = Math.min((page + 1) * PAGE_SIZE, total);

  return (
    <section className={styles.list} aria-label="Список писем">
      <div className={styles.tabs} role="tablist">
        {tabs.map((tab) => (
          <button
            key={tab.label}
            type="button"
            role="tab"
            aria-selected={unreadOnly === tab.unread}
            className={cx(styles.tab, unreadOnly === tab.unread && styles.activeTab)}
            onClick={() => {
              dispatch(unreadOnlyChanged(tab.unread));
            }}
          >
            {tab.label}
          </button>
        ))}
      </div>
      {query ? <p className={styles.query}>Результаты поиска: «{query}»</p> : null}
      <div className={cx(styles.items, isFetching && styles.fetching)}>
        {error ? (
          <Notice
            tone="danger"
            title="Не удалось загрузить письма"
            action={
              <Button size="sm" onClick={() => void refetch()}>
                Повторить
              </Button>
            }
          >
            {getErrorMessage(error)}
          </Notice>
        ) : isLoading ? (
          Array.from({ length: 6 }, (_, index) => (
            <div key={index} className={styles.skeleton}>
              <Skeleton width="45%" height={14} />
              <Skeleton width="80%" height={12} />
            </div>
          ))
        ) : data?.items.length === 0 ? (
          <EmptyState
            icon={<Inbox size={36} strokeWidth={1.5} />}
            title={query ? 'Ничего не найдено' : 'Писем нет'}
            text={query ? 'Попробуйте изменить запрос.' : 'В этой папке пока пусто.'}
          />
        ) : (
          data?.items.map((message) => (
            <MessageListItem
              key={message.uid}
              message={message}
              showRecipient={showRecipient}
              selected={message.uid === selectedUid}
              onSelect={(uid) => {
                dispatch(messageSelected(uid));
              }}
            />
          ))
        )}
      </div>
      {total > 0 ? (
        <div className={styles.pager}>
          <span>
            {first}–{last} из {total}
          </span>
          <IconButton
            label="Предыдущая страница"
            icon={<ChevronLeft size={20} />}
            disabled={page === 0}
            onClick={() => {
              dispatch(pageChanged(page - 1));
            }}
          />
          <IconButton
            label="Следующая страница"
            icon={<ChevronRight size={20} />}
            disabled={last >= total}
            onClick={() => {
              dispatch(pageChanged(page + 1));
            }}
          />
        </div>
      ) : null}
    </section>
  );
};
