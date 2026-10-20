import { Paperclip, Save, Send, X } from 'lucide-react';
import { useRef, useState } from 'react';

import {
  useDeleteMessageMutation,
  useSaveDraftMutation,
  useSendMessageMutation,
  type SendRequest,
} from '@/entities/mailbox';
import { getErrorMessage } from '@/shared/api';
import { useAppDispatch, useAppSelector } from '@/shared/lib/store';
import { showToast } from '@/shared/lib/toast';
import { Button, IconButton, Modal, Notice, TextField } from '@/shared/ui';

import styles from './ComposeModal.module.css';
import { fileToBase64, invalidAddresses, splitAddresses } from '../../lib/files';
import {
  composeClosed,
  selectComposeInit,
  selectComposeSeq,
  type ComposeInit,
} from '../../model/composeSlice';
import { AskAiPanel } from '../AskAiPanel/AskAiPanel';

const MAX_ATTACHMENTS = 20;

interface ComposeFormProps {
  accountId: number;
  init: ComposeInit;
}

const ComposeForm = ({ accountId, init }: ComposeFormProps) => {
  const dispatch = useAppDispatch();
  const [to, setTo] = useState(init.to);
  const [cc, setCc] = useState(init.cc);
  const [bcc, setBcc] = useState(init.bcc);
  const [showCopies, setShowCopies] = useState(Boolean(init.cc || init.bcc));
  const [subject, setSubject] = useState(init.subject);
  const [body, setBody] = useState(init.body);
  const [files, setFiles] = useState<File[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);
  const [send] = useSendMessageMutation();
  const [saveDraft] = useSaveDraftMutation();
  const [deleteMessage] = useDeleteMessageMutation();

  const close = () => {
    dispatch(composeClosed());
  };

  const buildRequest = async (): Promise<SendRequest | null> => {
    const lists = { to: splitAddresses(to), cc: splitAddresses(cc), bcc: splitAddresses(bcc) };
    const bad = invalidAddresses([...lists.to, ...lists.cc, ...lists.bcc]);
    if (bad.length > 0) {
      setError(`Некорректный адрес: ${bad.join(', ')}`);
      return null;
    }
    const attachments = await Promise.all(
      files.map(async (file) => ({
        filename: file.name,
        content_type: file.type || 'application/octet-stream',
        content_base64: await fileToBase64(file),
      })),
    );
    return {
      ...lists,
      subject,
      text: body,
      attachments,
      in_reply_to: init.inReplyTo,
      references: init.references,
      answered: init.answered,
    };
  };

  const dropReplacedDraft = async () => {
    if (!init.replaces) {
      return;
    }
    try {
      await deleteMessage({ accountId, ...init.replaces, permanent: true }).unwrap();
    } catch {
      // Новое письмо или черновик уже сохранены; старый черновик останется.
    }
  };

  const run = async (
    action: (request: SendRequest) => Promise<void>,
    requireRecipients: boolean,
  ) => {
    setError(null);
    setBusy(true);
    try {
      const request = await buildRequest();
      if (!request) {
        return;
      }
      if (requireRecipients && request.to.length + request.cc.length + request.bcc.length === 0) {
        setError('Укажите хотя бы одного получателя.');
        return;
      }
      await action(request);
      await dropReplacedDraft();
      close();
    } catch (cause) {
      setError(getErrorMessage(cause));
    } finally {
      setBusy(false);
    }
  };

  const handleSend = () =>
    run(async (request) => {
      const result = await send({ accountId, body: request }).unwrap();
      showToast(
        result.saved_to_sent
          ? 'Письмо отправлено'
          : 'Письмо отправлено, но копия не сохранена в «Отправленные»',
        result.saved_to_sent ? 'success' : 'warning',
      );
    }, true);

  const handleSaveDraft = () =>
    run(async (request) => {
      await saveDraft({ accountId, body: request }).unwrap();
      showToast('Черновик сохранён', 'success');
    }, false);

  const addFiles = (list: FileList | null) => {
    if (!list) {
      return;
    }
    setFiles((current) => [...current, ...Array.from(list)].slice(0, MAX_ATTACHMENTS));
  };

  return (
    <Modal
      open
      onClose={close}
      title={init.answered ? 'Ответ' : 'Новое письмо'}
      footer={
        <div className={styles.footer}>
          <Button
            variant="primary"
            icon={<Send size={18} />}
            disabled={busy}
            onClick={() => void handleSend()}
          >
            {busy ? 'Подождите…' : 'Отправить'}
          </Button>
          <Button
            variant="secondary"
            icon={<Save size={18} />}
            disabled={busy}
            onClick={() => void handleSaveDraft()}
          >
            Сохранить черновик
          </Button>
          <Button variant="ghost" disabled={busy} onClick={close}>
            Отмена
          </Button>
        </div>
      }
    >
      <div className={styles.form}>
        <TextField
          label="Кому"
          placeholder="Кому (через запятую)"
          autoFocus={!init.to}
          value={to}
          onChange={setTo}
          trailing={
            showCopies ? null : (
              <Button
                variant="link"
                size="sm"
                onClick={() => {
                  setShowCopies(true);
                }}
              >
                Копия
              </Button>
            )
          }
        />
        {showCopies ? (
          <>
            <TextField label="Копия" placeholder="Копия" value={cc} onChange={setCc} />
            <TextField
              label="Скрытая копия"
              placeholder="Скрытая копия"
              value={bcc}
              onChange={setBcc}
            />
          </>
        ) : null}
        <TextField label="Тема" placeholder="Тема" value={subject} onChange={setSubject} />
        <textarea
          className={styles.body}
          aria-label="Текст письма"
          placeholder="Текст письма"
          autoFocus={Boolean(init.to)}
          value={body}
          onChange={(event) => {
            setBody(event.target.value);
          }}
        />
        {files.length > 0 ? (
          <ul className={styles.files}>
            {files.map((file, index) => (
              <li key={`${file.name}-${String(index)}`} className={styles.file}>
                <Paperclip size={16} />
                <span className={styles.fileName}>{file.name}</span>
                <IconButton
                  label={`Убрать ${file.name}`}
                  size="sm"
                  icon={<X size={16} />}
                  onClick={() => {
                    setFiles((current) => current.filter((_, i) => i !== index));
                  }}
                />
              </li>
            ))}
          </ul>
        ) : null}
        <div>
          <input
            ref={fileInput}
            type="file"
            multiple
            hidden
            data-testid="compose-file-input"
            onChange={(event) => {
              addFiles(event.target.files);
              event.target.value = '';
            }}
          />
          <Button
            variant="soft"
            size="sm"
            icon={<Paperclip size={16} />}
            onClick={() => fileInput.current?.click()}
          >
            Прикрепить файл
          </Button>
        </div>
        <AskAiPanel body={body} subject={subject} recipients={to} thread={init.thread} />
        {error ? <Notice tone="danger">{error}</Notice> : null}
      </div>
    </Modal>
  );
};

interface ComposeModalProps {
  accountId: number | null;
}

/** Окно написания, ответа и пересылки. Открывается экшеном `composeOpened`. */
export const ComposeModal = ({ accountId }: ComposeModalProps) => {
  const init = useAppSelector(selectComposeInit);
  const seq = useAppSelector(selectComposeSeq);
  if (!init || accountId === null) {
    return null;
  }
  return <ComposeForm key={seq} accountId={accountId} init={init} />;
};
