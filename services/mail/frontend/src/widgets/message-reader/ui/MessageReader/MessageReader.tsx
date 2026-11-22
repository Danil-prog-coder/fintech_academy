import {
  Download,
  FolderInput,
  Forward,
  MailOpen,
  Mail as MailIcon,
  Pencil,
  Reply,
  ReplyAll,
  Star,
  Trash2,
} from 'lucide-react';

import {
  addressFull,
  downloadAttachment,
  folderLabel,
  formatFullDate,
  formatSize,
  messageSelected,
  MessageBody,
  selectFolder,
  selectSelectedUid,
  useActiveAccount,
  useDeleteMessageMutation,
  useGetMessageQuery,
  useListFoldersQuery,
  useUpdateMessage,
  type Attachment,
  type MailMessage,
  type MessageRef,
} from '@/entities/mailbox';
import {
  buildDraftEdit,
  buildForward,
  buildReply,
  composeOpened,
} from '@/features/compose-message';
import { getErrorMessage } from '@/shared/api';
import { useAppDispatch, useAppSelector } from '@/shared/lib/store';
import { showToast } from '@/shared/lib/toast';
import { Avatar, Button, DropdownMenu, EmptyState, IconButton, Notice, Spinner } from '@/shared/ui';

import styles from './MessageReader.module.css';

interface OpenMessageProps {
  message: MailMessage;
  accountId: number;
  ownEmail: string;
}

const OpenMessage = ({ message, accountId, ownEmail }: OpenMessageProps) => {
  const dispatch = useAppDispatch();
  const { data: folders } = useListFoldersQuery(accountId);
  const [updateMessage] = useUpdateMessage();
  const [deleteMessage] = useDeleteMessageMutation();
  const ref: MessageRef = { accountId, folder: message.folder, uid: message.uid };
  const role = folders?.find((item) => item.path === message.folder)?.role;
  const inTrash = role === 'trash';

  const attempt = async (action: () => Promise<unknown>, failure: string) => {
    try {
      await action();
    } catch (cause) {
      showToast(getErrorMessage(cause, failure), 'danger');
    }
  };

  const handleDelete = () => {
    if (inTrash && !window.confirm('Удалить письмо безвозвратно?')) {
      return;
    }
    void attempt(async () => {
      await deleteMessage(ref).unwrap();
      dispatch(messageSelected(null));
      showToast(inTrash ? 'Письмо удалено' : 'Письмо перенесено в корзину', 'success');
    }, 'Не удалось удалить письмо');
  };

  const moveTargets = (folders ?? []).filter((item) => item.path !== message.folder);

  const handleDownload = (attachment: Attachment) => {
    void attempt(() => downloadAttachment(ref, attachment), 'Не удалось скачать вложение');
  };

  const files = message.attachments.filter((attachment) => !attachment.inline);
  const sender = message.sender;

  return (
    <article className={styles.message}>
      <div className={styles.toolbar} role="toolbar" aria-label="Действия с письмом">
        {role === 'drafts' ? (
          <Button
            variant="primary"
            icon={<Pencil size={18} />}
            onClick={() => {
              dispatch(composeOpened(buildDraftEdit(message)));
            }}
          >
            Редактировать
          </Button>
        ) : (
          <>
            <Button
              variant="primary"
              icon={<Reply size={18} />}
              onClick={() => {
                dispatch(composeOpened(buildReply(message, ownEmail, false)));
              }}
            >
              Ответить
            </Button>
            <Button
              icon={<ReplyAll size={18} />}
              onClick={() => {
                dispatch(composeOpened(buildReply(message, ownEmail, true)));
              }}
            >
              Всем
            </Button>
            <Button
              icon={<Forward size={18} />}
              onClick={() => {
                dispatch(composeOpened(buildForward(message)));
              }}
            >
              Переслать
            </Button>
          </>
        )}
        <span className={styles.spacer} />
        <IconButton
          label={message.flagged ? 'Снять флажок' : 'Поставить флажок'}
          active={message.flagged}
          icon={<Star size={20} />}
          onClick={() => {
            void attempt(
              () => updateMessage(ref, { flagged: !message.flagged }),
              'Не удалось изменить флажок',
            );
          }}
        />
        <IconButton
          label={message.seen ? 'Пометить непрочитанным' : 'Пометить прочитанным'}
          icon={message.seen ? <MailIcon size={20} /> : <MailOpen size={20} />}
          onClick={() => {
            void attempt(
              () => updateMessage(ref, { seen: !message.seen }),
              'Не удалось изменить статус',
            );
          }}
        />
        {moveTargets.length > 0 ? (
          <DropdownMenu
            label="Переместить в папку"
            trigger={<FolderInput size={20} />}
            items={moveTargets.map((target) => ({
              id: target.path,
              label: folderLabel(target),
              onSelect: () => {
                void attempt(async () => {
                  await updateMessage(ref, { move_to: target.path });
                  dispatch(messageSelected(null));
                  showToast(`Перенесено: ${folderLabel(target)}`, 'success');
                }, 'Не удалось перенести письмо');
              },
            }))}
          />
        ) : null}
        <IconButton
          label={inTrash ? 'Удалить навсегда' : 'В корзину'}
          icon={<Trash2 size={20} />}
          onClick={handleDelete}
        />
      </div>

      <h2 className={styles.subject}>{message.subject || '(без темы)'}</h2>
      <header className={styles.header}>
        <Avatar
          initials={(sender?.name ?? sender?.email ?? '?').slice(0, 1).toUpperCase()}
          size="lg"
        />
        <div className={styles.meta}>
          <span className={styles.from}>
            {sender ? addressFull(sender) : 'Неизвестный отправитель'}
          </span>
          <span className={styles.recipients}>
            Кому: {message.to.map(addressFull).join(', ') || '—'}
          </span>
          {message.cc.length > 0 ? (
            <span className={styles.recipients}>
              Копия: {message.cc.map(addressFull).join(', ')}
            </span>
          ) : null}
        </div>
        <time className={styles.date} dateTime={message.date ?? undefined}>
          {formatFullDate(message.date)}
        </time>
      </header>

      {message.remote_images_blocked ? (
        <Notice tone="info" compact>
          Внешние изображения заблокированы для вашей безопасности.
        </Notice>
      ) : null}

      <div className={styles.body}>
        <MessageBody html={message.html} text={message.text} />
      </div>

      {files.length > 0 ? (
        <section className={styles.attachments} aria-label="Вложения">
          <h3 className={styles.attachmentsTitle}>Вложения ({files.length})</h3>
          <ul className={styles.attachmentList}>
            {files.map((attachment) => (
              <li key={attachment.index}>
                <button
                  type="button"
                  className={styles.attachment}
                  onClick={() => {
                    handleDownload(attachment);
                  }}
                >
                  <Download size={18} />
                  <span className={styles.attachmentName}>{attachment.filename}</span>
                  <span className={styles.attachmentSize}>{formatSize(attachment.size)}</span>
                </button>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </article>
  );
};

export const MessageReader = () => {
  const { account } = useActiveAccount();
  const folder = useAppSelector(selectFolder);
  const uid = useAppSelector(selectSelectedUid);
  const { data, isFetching, error, refetch } = useGetMessageQuery(
    { accountId: account?.id ?? 0, folder, uid: uid ?? 0 },
    { skip: !account || uid === null },
  );

  if (!account || uid === null) {
    return (
      <div className={styles.placeholder}>
        <EmptyState title="Выберите письмо" text="Содержимое появится здесь." />
      </div>
    );
  }
  if (error) {
    return (
      <div className={styles.placeholder}>
        <Notice
          tone="danger"
          title="Не удалось открыть письмо"
          action={
            <Button size="sm" onClick={() => void refetch()}>
              Повторить
            </Button>
          }
        >
          {getErrorMessage(error)}
        </Notice>
      </div>
    );
  }
  if (!data || (isFetching && data.uid !== uid)) {
    return (
      <div className={styles.placeholder}>
        <Spinner size="lg" label="Загрузка письма" />
      </div>
    );
  }
  return (
    <div className={styles.scroll}>
      <OpenMessage
        key={`${data.folder}:${String(data.uid)}`}
        message={data}
        accountId={account.id}
        ownEmail={account.email}
      />
    </div>
  );
};
