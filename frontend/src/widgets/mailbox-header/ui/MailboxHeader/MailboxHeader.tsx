import { GitBranch, House, LogOut, MessageSquare, Plug, Search, Unplug } from 'lucide-react';
import { type SubmitEventHandler, useState } from 'react';
import { useNavigate } from 'react-router';

import {
  accountSelected,
  queryChanged,
  selectQuery,
  useActiveAccount,
  useDisconnectAccountMutation,
} from '@/entities/mailbox';
import { useGetMeQuery, useLogout } from '@/entities/session';
import { routePaths } from '@/shared/config';
import { useAppDispatch, useAppSelector } from '@/shared/lib/store';
import { showToast } from '@/shared/lib/toast';
import { Avatar, DropdownMenu, TextField } from '@/shared/ui';

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

export const MailboxHeader = () => {
  const dispatch = useAppDispatch();
  const navigate = useNavigate();
  const logout = useLogout();
  const query = useAppSelector(selectQuery);
  const { account } = useActiveAccount();
  const { data: me } = useGetMeQuery(undefined);
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

  const email = me?.email ?? '';

  return (
    <header className={styles.header}>
      <h1 className={styles.title}>Почта</h1>
      {/* Запрос меняется извне при смене папки или ящика — ключ пересоздаёт поле. */}
      <SearchBox key={query} query={query} />
      <DropdownMenu
        label="Меню пользователя"
        trigger={
          <span className={styles.user}>
            <Avatar initials={(email.slice(0, 2) || '?').toUpperCase()} size="md" />
            <span className={styles.email}>{email}</span>
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
          {
            id: 'home',
            label: 'Главная',
            icon: <House size={18} />,
            onSelect: () => {
              void navigate(routePaths.root);
            },
          },
          {
            id: 'repo',
            label: 'Репозиторий',
            icon: <GitBranch size={18} />,
            onSelect: () => {
              void navigate(routePaths.repo);
            },
          },
          {
            id: 'chat',
            label: 'Чат с ассистентом',
            icon: <MessageSquare size={18} />,
            onSelect: () => {
              void navigate(routePaths.chat);
            },
          },
          {
            id: 'logout',
            label: 'Выйти',
            icon: <LogOut size={18} />,
            onSelect: logout,
          },
        ]}
      />
    </header>
  );
};
