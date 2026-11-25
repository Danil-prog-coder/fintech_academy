import {
  Archive,
  Bookmark,
  File,
  FileText,
  Folder,
  Inbox,
  Layers,
  OctagonAlert,
  Pencil,
  Send,
  Star,
  Trash,
  type LucideIcon,
} from 'lucide-react';

import {
  accountSelected,
  folderLabel,
  folderSelected,
  selectFolder,
  useActiveAccount,
  useListFoldersQuery,
  type MailFolder,
} from '@/entities/mailbox';
import { composeOpened, emptyCompose } from '@/features/compose-message';
import { cx } from '@/shared/lib/cx';
import { useAppDispatch, useAppSelector } from '@/shared/lib/store';
import { Button, Select, Skeleton } from '@/shared/ui';

import styles from './MailboxSidebar.module.css';

const roleIcons: Record<string, LucideIcon> = {
  inbox: Inbox,
  sent: Send,
  drafts: FileText,
  trash: Trash,
  junk: OctagonAlert,
  archive: Archive,
  all: Layers,
  flagged: Star,
  important: Bookmark,
};

/**
 * Счётчик рядом с папкой. Непрочитанные имеют смысл только там, куда письма приходят:
 * во «Входящих», «Спаме» и своих папках. В «Черновиках» показываем, сколько их всего.
 * В «Отправленных», «Корзине», «Архиве» и служебных папках Gmail («Вся почта»,
 * «Помеченные», «Важное») число непрочитанных вводит в заблуждение — его не показываем.
 */
const folderCounter = (folder: MailFolder): { value: number; label: string } | null => {
  switch (folder.role) {
    case 'drafts':
      return folder.total > 0 ? { value: folder.total, label: 'Черновиков' } : null;
    case 'sent':
    case 'trash':
    case 'archive':
    case 'all':
    case 'flagged':
    case 'important':
      return null;
    default:
      return folder.unseen > 0 ? { value: folder.unseen, label: 'Непрочитанных' } : null;
  }
};

const FolderIcon = ({ folder }: { folder: MailFolder }) => {
  const Icon =
    (folder.role ? roleIcons[folder.role] : undefined) ??
    (folder.name === 'INBOX' ? Inbox : Folder);
  return <Icon size={22} strokeWidth={1.8} />;
};

export const MailboxSidebar = () => {
  const dispatch = useAppDispatch();
  const currentFolder = useAppSelector(selectFolder);
  const { account, accounts } = useActiveAccount();
  const {
    data: folders,
    isLoading,
    isError,
  } = useListFoldersQuery(account?.id ?? 0, {
    skip: !account,
  });

  return (
    <aside className={styles.sidebar}>
      {accounts.length > 1 && account ? (
        <Select
          label="Почтовый ящик"
          fullWidth
          value={String(account.id)}
          options={accounts.map((item) => ({ value: String(item.id), label: item.email }))}
          onChange={(value) => {
            dispatch(accountSelected(Number(value)));
          }}
        />
      ) : (
        <p className={styles.account}>{account?.email}</p>
      )}
      <Button
        variant="primary"
        size="lg"
        fullWidth
        icon={<Pencil size={20} />}
        onClick={() => {
          dispatch(composeOpened(emptyCompose));
        }}
      >
        Написать письмо
      </Button>
      <nav className={styles.nav} aria-label="Папки">
        {isLoading
          ? Array.from({ length: 5 }, (_, index) => (
              <div key={index} className={styles.skeleton}>
                <Skeleton width="70%" height={14} />
              </div>
            ))
          : null}
        {isError ? <p className={styles.error}>Не удалось загрузить папки.</p> : null}
        {folders?.map((folder) => {
          const active = folder.path === currentFolder;
          const counter = folderCounter(folder);
          return (
            <button
              key={folder.path}
              type="button"
              className={cx(styles.folder, active && styles.active)}
              aria-current={active ? 'page' : undefined}
              onClick={() => {
                dispatch(folderSelected(folder.path));
              }}
            >
              <FolderIcon folder={folder} />
              <span className={styles.label}>{folderLabel(folder)}</span>
              {counter ? (
                <span
                  className={styles.count}
                  title={`${counter.label}: ${String(counter.value)}`}
                  aria-label={`${counter.label}: ${String(counter.value)}`}
                >
                  {counter.value}
                </span>
              ) : null}
            </button>
          );
        })}
        {folders?.length === 0 ? (
          <p className={styles.error}>
            <File size={16} /> Папок нет
          </p>
        ) : null}
      </nav>
    </aside>
  );
};
