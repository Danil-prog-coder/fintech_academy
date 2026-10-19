import { CircleQuestionMark, LayoutDashboard, Plug, Search } from 'lucide-react';
import { useNavigate } from 'react-router';

import { searchChanged, selectSearch } from '@/entities/letter';
import { currentUser, UserChip } from '@/entities/user';
import { AiSearchToggle } from '@/features/ai-search';
import { selectAiAvailable } from '@/features/connect-source';
import { routePaths } from '@/shared/config';
import { useAppDispatch, useAppSelector } from '@/shared/lib/store';
import { showToast } from '@/shared/lib/toast';
import { DropdownMenu, IconButton, TextField } from '@/shared/ui';

import styles from './MailHeader.module.css';

export const MailHeader = () => {
  const dispatch = useAppDispatch();
  const navigate = useNavigate();
  const search = useAppSelector(selectSearch);
  const aiAvailable = useAppSelector(selectAiAvailable);

  return (
    <header className={styles.header}>
      <h1 className={styles.title}>Почта</h1>
      <TextField
        className={styles.search}
        label="Поиск по письмам"
        placeholder="Поиск по письмам, отправителям, темам…"
        value={search}
        onChange={(value) => {
          dispatch(searchChanged(value));
        }}
        icon={<Search size={20} />}
        clearable
      />
      <AiSearchToggle disabled={!aiAvailable} />
      <IconButton
        label="Помощь"
        icon={<CircleQuestionMark size={24} strokeWidth={1.8} />}
        onClick={() => {
          showToast(
            '«Подготовить ответ» — в открытом письме, «AI-поиск» — в правой панели. Письма отправляете только вы.',
          );
        }}
      />
      <DropdownMenu
        label="Меню пользователя"
        trigger={<UserChip user={currentUser} />}
        items={[
          {
            id: 'connect',
            label: 'Подключения',
            icon: <Plug size={18} />,
            onSelect: () => {
              void navigate(routePaths.connect);
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
    </header>
  );
};
