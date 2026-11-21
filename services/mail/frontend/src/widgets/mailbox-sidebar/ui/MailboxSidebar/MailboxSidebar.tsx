import {
  Archive,
  File,
  FileText,
  Folder,
  Inbox,
  Mail,
  OctagonAlert,
  Pencil,
  Send,
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
      <div className={styles.brand}>
        <Mail size={30} strokeWidth={1.8} />
        <span className={styles.brandName}>Почта</span>
      </div>
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
              {folder.unseen > 0 && folder.role !== 'trash' ? (
                <span
                  className={styles.count}
                  aria-label={`Непрочитанных: ${String(folder.unseen)}`}
                >
                  {folder.unseen}
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
