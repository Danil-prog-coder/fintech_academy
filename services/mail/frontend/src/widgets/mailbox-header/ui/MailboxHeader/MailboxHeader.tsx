import { ChevronDown, Mail, Plug, Search, Unplug } from 'lucide-react';
import { type SubmitEventHandler, useState } from 'react';
import { useNavigate } from 'react-router';

import {
  accountSelected,
  queryChanged,
  selectQuery,
  useActiveAccount,
  useDisconnectAccountMutation,
} from '@/entities/mailbox';
import { routePaths } from '@/shared/config';
import { useAppDispatch, useAppSelector } from '@/shared/lib/store';
import { showToast } from '@/shared/lib/toast';
import { DropdownMenu, TextField } from '@/shared/ui';

import styles from './MailboxHeader.module.css';

interface SearchBoxProps {
  query: string;
}

const SearchBox = ({ query }: SearchBoxProps) => {
  const dispatch = useAppDispatch();
  const [draft, setDraft] = useState(query);

  const handleSearch: SubmitEventHandler<HTMLFormElement> = (event) => {
    event.preventDefault();
    dispatch(queryChanged(draft.trim()));
  };

  return (
    <form className={styles.searchForm} role="search" onSubmit={handleSearch}>
      <TextField
        className={styles.search}
        label="Поиск по письмам"
        placeholder="Поиск по письмам в этой папке — Enter"
        value={draft}
        onChange={(value) => {
          setDraft(value);
          if (!value) {
            dispatch(queryChanged(''));
          }
        }}
        icon={<Search size={20} />}
        clearable
      />
    </form>
  );
};

/**
 * Панель над списком писем: поиск и действия с ящиком. Навигация по разделам и меню
 * пользователя — в общей шапке сайта (AppHeader) над ней.
 */
export const MailboxHeader = () => {
  const dispatch = useAppDispatch();
  const navigate = useNavigate();
  const query = useAppSelector(selectQuery);
  const { account } = useActiveAccount();
  const [disconnect] = useDisconnectAccountMutation();
  const handleDisconnect = async () => {
    if (!account || !window.confirm(`Отключить ящик ${account.email}?`)) {
      return;
    }
    try {
      await disconnect(account.id).unwrap();
      dispatch(accountSelected(null));
      showToast('Ящик отключён', 'success');
    } catch {
      showToast('Не удалось отключить ящик', 'danger');
    }
  };

  const mailbox = account?.email ?? '';

  return (
    <header className={styles.header}>
      <h1 className={styles.title}>Почта</h1>
      {/* Запрос меняется извне при смене папки или ящика — ключ пересоздаёт поле. */}
      <SearchBox key={query} query={query} />
      <DropdownMenu
        label="Действия с ящиком"
        trigger={
          <span className={styles.mailbox}>
            <Mail size={18} />
            <span className={styles.email} title={mailbox}>
              Ящик
            </span>
            <ChevronDown size={16} />
          </span>
        }
        items={[
          {
            id: 'connect',
            label: 'Подключить ещё ящик',
            icon: <Plug size={18} />,
            onSelect: () => {
              void navigate(routePaths.connect);
            },
          },
          {
            id: 'disconnect',
            label: 'Отключить этот ящик',
            icon: <Unplug size={18} />,
            danger: true,
            onSelect: () => {
              void handleDisconnect();
            },
          },
        ]}
      />
    </header>
  );
};
