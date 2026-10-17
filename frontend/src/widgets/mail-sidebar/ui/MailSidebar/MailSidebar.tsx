import {
  Archive,
  Clock,
  FileText,
  Inbox,
  Mail,
  Pencil,
  Send,
  Star,
  Trash,
  type LucideIcon,
} from 'lucide-react';

import {
  folderSelected,
  selectFolder,
  useGetLettersQuery,
  type LetterFolder,
} from '@/entities/letter';
import { cx } from '@/shared/lib/cx';
import { useAppDispatch, useAppSelector } from '@/shared/lib/store';
import { showToast } from '@/shared/lib/toast';
import { Button } from '@/shared/ui';

import styles from './MailSidebar.module.css';

interface FolderItem {
  id: LetterFolder;
  label: string;
  icon: LucideIcon;
}

const folders: FolderItem[] = [
  { id: 'inbox', label: 'Входящие', icon: Inbox },
  { id: 'starred', label: 'Помеченные', icon: Star },
  { id: 'snoozed', label: 'Отложенные', icon: Clock },
  { id: 'sent', label: 'Отправленные', icon: Send },
  { id: 'drafts', label: 'Черновики', icon: FileText },
  { id: 'archive', label: 'Архив', icon: Archive },
  { id: 'trash', label: 'Корзина', icon: Trash },
];

interface MailSidebarProps {
  draftsCount: number;
  starredCount: number;
}

export const MailSidebar = ({ draftsCount, starredCount }: MailSidebarProps) => {
  const dispatch = useAppDispatch();
  const folder = useAppSelector(selectFolder);
  const { data: inbox } = useGetLettersQuery('inbox');
  const unread = inbox?.filter((letter) => letter.unread).length ?? 0;

  const counters: Partial<Record<LetterFolder, number>> = {
    inbox: unread,
    starred: starredCount,
    drafts: draftsCount,
  };

  return (
    <aside className={styles.sidebar}>
      <div className={styles.brand}>
        <Mail size={30} strokeWidth={1.8} />
        <span className={styles.brandName}>Рабочая почта</span>
      </div>
      <Button
        variant="primary"
        size="lg"
        fullWidth
        icon={<Pencil size={20} />}
        onClick={() => {
          showToast('Новое письмо открывается в почтовом клиенте (демо)');
        }}
      >
        Написать письмо
      </Button>
      <nav className={styles.nav} aria-label="Папки">
        {folders.map(({ id, label, icon: Icon }) => {
          const count = counters[id];
          const active = folder === id;
          return (
            <button
              key={id}
              type="button"
              className={cx(styles.folder, active && styles.active)}
              aria-current={active ? 'page' : undefined}
              onClick={() => {
                dispatch(folderSelected(id));
              }}
            >
              <Icon size={22} strokeWidth={1.8} />
              <span className={styles.label}>{label}</span>
              {count ? <span className={styles.count}>{count}</span> : null}
            </button>
          );
        })}
      </nav>
    </aside>
  );
};
