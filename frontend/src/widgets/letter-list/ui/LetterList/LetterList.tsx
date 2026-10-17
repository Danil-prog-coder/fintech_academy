import { ArrowUpDown, Inbox } from 'lucide-react';

import {
  filterChanged,
  filterLetters,
  letterSelected,
  LetterListItem,
  selectFilter,
  selectFolder,
  selectSearch,
  selectSelectedLetterId,
  useGetLettersQuery,
  type LetterFilter,
} from '@/entities/letter';
import { cx } from '@/shared/lib/cx';
import { useAppDispatch, useAppSelector } from '@/shared/lib/store';
import { showToast } from '@/shared/lib/toast';
import { EmptyState, IconButton, Skeleton } from '@/shared/ui';

import styles from './LetterList.module.css';

const tabs: { id: LetterFilter; label: string }[] = [
  { id: 'all', label: 'Все письма' },
  { id: 'unread', label: 'Непрочитанные' },
  { id: 'attachments', label: 'С вложениями' },
];

export const LetterList = () => {
  const dispatch = useAppDispatch();
  const folder = useAppSelector(selectFolder);
  const filter = useAppSelector(selectFilter);
  const search = useAppSelector(selectSearch);
  const selectedId = useAppSelector(selectSelectedLetterId);
  const { data: letters, isLoading } = useGetLettersQuery(folder);

  const visible = filterLetters(letters ?? [], filter, search);

  return (
    <section className={styles.list} aria-label="Список писем">
      <div className={styles.tabs} role="tablist">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            type="button"
            role="tab"
            aria-selected={filter === tab.id}
            className={cx(styles.tab, filter === tab.id && styles.activeTab)}
            onClick={() => {
              dispatch(filterChanged(tab.id));
            }}
          >
            {tab.label}
          </button>
        ))}
        <IconButton
          className={styles.sort}
          label="Сортировка: сначала новые"
          icon={<ArrowUpDown size={20} />}
          onClick={() => {
            showToast('Письма отсортированы: сначала новые');
          }}
        />
      </div>
      <div className={styles.items}>
        {isLoading ? (
          Array.from({ length: 5 }, (_, index) => (
            <div key={index} className={styles.skeleton}>
              <Skeleton width="45%" height={14} />
              <Skeleton width="80%" height={12} />
              <Skeleton width="65%" height={12} />
            </div>
          ))
        ) : visible.length === 0 ? (
          <EmptyState
            icon={<Inbox size={36} strokeWidth={1.5} />}
            title={search ? 'Ничего не найдено' : 'Папка пуста'}
            text={search ? 'Попробуйте изменить запрос.' : 'Здесь пока нет писем.'}
          />
        ) : (
          visible.map((letter) => (
            <LetterListItem
              key={letter.id}
              letter={letter}
              selected={letter.id === selectedId}
              onSelect={(id) => {
                dispatch(letterSelected(id));
              }}
            />
          ))
        )}
      </div>
    </section>
  );
};
