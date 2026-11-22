import { LifeBuoy, MessageSquarePlus, Mic, Paperclip, Send, Square, X } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router';

import {
  ActionBadge,
  AnswerImages,
  describeAskError,
  FeedbackButtons,
  SourceList,
  useAskMutation,
  useContactSupportMutation,
  useGetPopularQuery,
  useResetChatMutation,
  useTranscribeMutation,
  type Answer,
  type AskErrorInfo,
} from '@/entities/qa';
import { getErrorMessage } from '@/shared/api';
import { routePaths } from '@/shared/config';
import { Button, EmptyState, IconButton, Notice, Spinner } from '@/shared/ui';

import styles from './ChatPanel.module.css';
import { recordVoice } from '../../lib/voiceRecording';
import { VoicePlayer } from '../VoicePlayer/VoicePlayer';

interface Attachment {
  id: string;
  name: string;
}

interface Turn {
  id: number;
  question: string;
  answer: Answer | null;
  attachments?: Attachment[];
  voice?: boolean;
  audio?: Blob;
}

const LEGACY_STORAGE_KEY = 'mail.chat';
const FILE_EXTENSIONS = [
  '.pdf',
  '.docx',
  '.txt',
  '.md',
  '.csv',
  '.png',
  '.jpg',
  '.jpeg',
  '.gif',
  '.webp',
];
const MAX_FILES = 3;
const MAX_FILE_SIZE = 5 * 1024 * 1024;
const MAX_QUESTION_LENGTH = 4000;

interface VoiceDraft {
  audio: Blob;
  transcript?: string;
}

const fileKey = (file: File) => `${file.name}:${file.size}:${file.lastModified}`;

const loadTurns = (
  historyKey: string | undefined,
  projectId: string | null | undefined,
): Turn[] => {
  if (!historyKey) {
    return [];
  }
  try {
    const history = sessionStorage.getItem(historyKey);
    if (history) {
      return (JSON.parse(history) as Turn[]).filter((turn) => turn.answer);
    }
    const legacy = sessionStorage.getItem(LEGACY_STORAGE_KEY);
    return legacy
      ? (JSON.parse(legacy) as Turn[]).filter((turn) => turn.answer?.project_id === projectId)
      : [];
  } catch {
    return [];
  }
};

const saveTurns = (historyKey: string, turns: Turn[]) => {
  try {
    const history = turns
      .filter((turn) => turn.answer)
      .slice(-30)
      .map(({ id, question, answer, attachments, voice }) => ({
        id,
        question,
        answer,
        attachments,
        voice,
      }));
    sessionStorage.setItem(historyKey, JSON.stringify(history));
  } catch {
    // без хранилища история не переживёт перезагрузку — не критично
  }
};

interface ChatPanelProps {
  historyKey: string | undefined;
  projectId: string | null | undefined;
}

/** Чат с ассистентом проекта: память диалога хранит платформа, здесь — только то, что видно на экране. */
export const ChatPanel = ({ historyKey, projectId }: ChatPanelProps) => {
  const [turns, setTurns] = useState<Turn[]>(() => loadTurns(historyKey, projectId));
  const [question, setQuestion] = useState('');
  const [files, setFiles] = useState<File[]>([]);
  const [voice, setVoice] = useState<VoiceDraft | null>(null);
  const [recording, setRecording] = useState<'starting' | 'active' | 'processing' | null>(null);
  const [pending, setPending] = useState(false);
  const [transcribing, setTranscribing] = useState(false);
  const [failure, setFailure] = useState<AskErrorInfo | null>(null);
  const [supportNote, setSupportNote] = useState<string | null>(null);
  const [ask] = useAskMutation();
  const [transcribe] = useTranscribeMutation();
  const [reset] = useResetChatMutation();
  const [contact, { isLoading: contacting }] = useContactSupportMutation();
  const popular = useGetPopularQuery(undefined);
  const bottom = useRef<HTMLDivElement>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const recordingController = useRef<AbortController | null>(null);
  const stopRecording = useRef<(() => void) | null>(null);
  const activeRequest = useRef<{ abort: () => void } | null>(null);
  const busy = pending || recording !== null;

  useEffect(() => {
    if (historyKey) {
      saveTurns(historyKey, turns);
    }
    bottom.current?.scrollIntoView({ block: 'end' });
  }, [historyKey, turns]);

  useEffect(
    () => () => {
      recordingController.current?.abort();
      activeRequest.current?.abort();
      activeRequest.current = null;
    },
    [],
  );

  const showError = (message: string) => {
    setFailure({ message, needsProject: false, retryable: false });
  };

  const addFiles = (selected: File[]) => {
    const combined = [...files];
    let error = '';
    for (const file of selected) {
      const extension = file.name.slice(file.name.lastIndexOf('.')).toLowerCase();
      if (!FILE_EXTENSIONS.includes(extension)) {
        error ||= `Формат файла «${file.name}» не поддерживается.`;
      } else if (!file.size || file.size > MAX_FILE_SIZE) {
        error ||= `Файл «${file.name}» должен быть непустым и не больше 5 МБ.`;
      } else if (!combined.some((saved) => fileKey(saved) === fileKey(file))) {
        if (combined.length >= MAX_FILES) {
          error ||= 'К сообщению можно прикрепить до трёх файлов.';
          break;
        }
        combined.push(file);
      }
    }
    setFiles(combined);
    if (error) {
      showError(error);
    } else {
      setFailure(null);
    }
  };

  const startRecording = async () => {
    if (recordingController.current || activeRequest.current || voice) {
      return;
    }
    setFailure(null);
    setRecording('starting');
    const controller = new AbortController();
    recordingController.current = controller;
    try {
      const audio = await recordVoice(
        controller.signal,
        (stop) => {
          stopRecording.current = stop;
          setRecording('active');
        },
        () => {
          stopRecording.current = null;
          if (!controller.signal.aborted) {
            setRecording('processing');
          }
        },
      );
      if (!controller.signal.aborted) {
        setVoice({ audio });
      }
    } catch (cause) {
      if (!controller.signal.aborted) {
        const message =
          cause instanceof DOMException
            ? 'Не удалось получить или обработать запись. Проверьте доступ к микрофону и попробуйте снова.'
            : cause instanceof Error
              ? cause.message
              : 'Не удалось записать голосовое сообщение.';
        showError(message);
      }
    } finally {
      recordingController.current = null;
      stopRecording.current = null;
      if (!controller.signal.aborted) {
        setRecording(null);
      }
    }
  };

  const submit = async (text: string) => {
    const q = text.trim();
    if ((!q && !files.length && !voice) || activeRequest.current || recordingController.current) {
      return;
    }
    setFailure(null);
    setSupportNote(null);
    setPending(true);
    const id = (turns.at(-1)?.id ?? 0) + 1;
    const turn: Turn = {
      id,
      question: q,
      answer: null,
      attachments: files.map((file) => ({ id: fileKey(file), name: file.name })),
      voice: Boolean(voice),
      audio: voice?.audio,
    };
    setTurns((current) => [...current, turn]);
    try {
      let transcript = voice?.transcript;
      if (voice && transcript === undefined) {
        setTranscribing(true);
        const request = transcribe(voice.audio);
        activeRequest.current = request;
        ({ text: transcript } = await request.unwrap());
        if (activeRequest.current !== request) {
          return;
        }
        setVoice({ ...voice, transcript });
        setTranscribing(false);
      }
      const message = [q, transcript].filter(Boolean).join('\n\n');
      if (message.length > MAX_QUESTION_LENGTH) {
        setTurns((current) => current.filter((t) => t.id !== id));
        showError(
          'Текст и расшифровка вместе превышают 4000 символов. Сократите текст или запишите сообщение заново.',
        );
        return;
      }
      setTurns((current) => current.map((t) => (t.id === id ? { ...t, question: message } : t)));
      const request = ask({ message, files });
      activeRequest.current = request;
      const answer = await request.unwrap();
      setTurns((current) => current.map((t) => (t.id === id ? { ...t, answer } : t)));
      setQuestion('');
      setFiles([]);
      setVoice(null);
    } catch (cause) {
      setTurns((current) => current.filter((t) => t.id !== id));
      setFailure(describeAskError(cause));
    } finally {
      activeRequest.current = null;
      setPending(false);
      setTranscribing(false);
    }
  };

  const toSupport = async (turn: Turn) => {
    try {
      const esc = await contact({
        message: turn.question || undefined,
        request_id: turn.answer?.request_id,
      }).unwrap();
      setSupportNote(`Обращение ${esc.key} создано. Ответ специалиста придёт в уведомления.`);
    } catch (cause) {
      setSupportNote(getErrorMessage(cause, 'Не удалось связаться с поддержкой.'));
    }
  };

  const newDialog = async () => {
    if (activeRequest.current || recordingController.current) {
      return;
    }
    setFailure(null);
    setSupportNote(null);
    setPending(true);
    try {
      const request = reset(undefined);
      activeRequest.current = request;
      await request.unwrap();
      setTurns([]);
      setQuestion('');
      setFiles([]);
      setVoice(null);
    } catch (cause) {
      setFailure(describeAskError(cause));
    } finally {
      activeRequest.current = null;
      setPending(false);
    }
  };

  return (
    <section className={styles.chat} aria-label="Чат с ассистентом">
      <div className={styles.toolbar}>
        <Button
          size="sm"
          icon={<MessageSquarePlus size={16} />}
          disabled={turns.length === 0 || busy}
          onClick={() => void newDialog()}
        >
          Новый диалог
        </Button>
      </div>
      <div className={styles.messages}>
        {turns.length === 0 ? (
          <EmptyState
            title="Задайте вопрос по документации проекта"
            text="Ассистент отвечает только по документации и показывает источники."
          />
        ) : null}
        {turns.length === 0 && popular.data?.questions.length ? (
          <div className={styles.toolbar}>
            {popular.data.questions.map((q) => (
              <Button
                key={q}
                size="sm"
                variant="secondary"
                disabled={busy}
                onClick={() => void submit(q)}
              >
                {q}
              </Button>
            ))}
          </div>
        ) : null}
        {turns.map((turn) => (
          <div key={turn.id}>
            <div className={styles.user}>
              {turn.voice ? (
                <div className={styles.voice}>
                  <span>Голосовое сообщение</span>
                  {turn.audio ? <VoicePlayer audio={turn.audio} /> : null}
                </div>
              ) : null}
              {turn.question ? <p className={styles.text}>{turn.question}</p> : null}
              {turn.attachments?.length ? (
                <ul className={styles.attachments} aria-label="Вложения">
                  {turn.attachments.map(({ id, name }) => (
                    <li key={id} className={styles.attachment}>
                      <Paperclip size={14} aria-hidden />
                      <span>{name}</span>
                    </li>
                  ))}
                </ul>
              ) : null}
            </div>
            {turn.answer ? (
              <article className={styles.assistant}>
                <ActionBadge action={turn.answer.action} />
                <p className={styles.text}>{turn.answer.text}</p>
                <AnswerImages images={turn.answer.images ?? []} />
                <SourceList sources={turn.answer.sources ?? []} />
                {turn.answer.question_id ? (
                  <Notice tone="info" compact>
                    Вопрос передан администраторам проекта — их ответ придёт в уведомления.
                  </Notice>
                ) : null}
                {turn.answer.escalation ? (
                  <Notice tone="info" compact>
                    Обращение {turn.answer.escalation.key} передано в поддержку.
                  </Notice>
                ) : null}
                {turn.answer.action === 'offer_operator' && !turn.answer.escalation ? (
                  <Button
                    size="sm"
                    icon={<LifeBuoy size={14} />}
                    disabled={contacting}
                    onClick={() => void toSupport(turn)}
                  >
                    Связаться с поддержкой
                  </Button>
                ) : null}
                {turn.answer.action === 'answer' ? (
                  <FeedbackButtons requestId={turn.answer.request_id} />
                ) : null}
              </article>
            ) : (
              <div className={styles.assistant}>
                <Spinner
                  size="sm"
                  label={transcribing ? 'Распознаём речь' : 'Ассистент отвечает'}
                />
              </div>
            )}
          </div>
        ))}
        <div ref={bottom} />
      </div>
      {supportNote ? <Notice tone="info">{supportNote}</Notice> : null}
      {failure ? (
        <Notice
          tone="danger"
          action={
            failure.needsProject ? (
              <Link to={routePaths.projects}>Перейти к проектам</Link>
            ) : undefined
          }
        >
          {failure.message}
          {failure.retryable ? ' Можно повторить.' : ''}
        </Notice>
      ) : null}
      <form
        className={styles.form}
        onSubmit={(event) => {
          event.preventDefault();
          void submit(question);
        }}
      >
        {!pending && files.length > 0 ? (
          <ul className={styles.attachments} aria-label="Прикреплённые файлы">
            {files.map((file) => (
              <li key={fileKey(file)} className={styles.attachment}>
                <Paperclip size={14} aria-hidden />
                <span>{file.name}</span>
                <IconButton
                  size="sm"
                  label={`Удалить файл ${file.name}`}
                  icon={<X size={14} />}
                  disabled={busy}
                  onClick={() => {
                    setFiles((current) => current.filter((saved) => saved !== file));
                    setFailure(null);
                  }}
                />
              </li>
            ))}
          </ul>
        ) : null}
        {!pending && voice ? (
          <div className={styles.voiceDraft}>
            <VoicePlayer audio={voice.audio} />
            <IconButton
              size="sm"
              label="Удалить голосовое сообщение"
              icon={<X size={16} />}
              disabled={busy}
              onClick={() => {
                setVoice(null);
                setFailure(null);
              }}
            />
          </div>
        ) : null}
        {recording ? (
          <p role="status" className={styles.recording}>
            {recording === 'starting'
              ? 'Ожидаем доступ к микрофону…'
              : recording === 'active'
                ? 'Идёт запись…'
                : 'Готовим запись…'}
          </p>
        ) : null}
        <textarea
          className={styles.input}
          aria-label="Вопрос"
          placeholder="Например: как оформить командировку? (Enter — отправить, Shift+Enter — перенос)"
          rows={2}
          maxLength={MAX_QUESTION_LENGTH}
          disabled={pending}
          value={question}
          onChange={(event) => {
            setQuestion(event.target.value);
          }}
          onKeyDown={(event) => {
            if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
              event.preventDefault();
              void submit(question);
            }
          }}
        />
        <div className={styles.controls}>
          <input
            ref={fileInput}
            type="file"
            multiple
            hidden
            accept={FILE_EXTENSIONS.join(',')}
            onChange={(event) => {
              addFiles(Array.from(event.currentTarget.files ?? []));
              event.currentTarget.value = '';
            }}
          />
          <IconButton
            label="Прикрепить файлы"
            icon={<Paperclip size={18} />}
            disabled={busy}
            onClick={() => fileInput.current?.click()}
          />
          <IconButton
            label={recording === 'active' ? 'Остановить запись' : 'Записать голосовое сообщение'}
            icon={recording === 'active' ? <Square size={18} /> : <Mic size={18} />}
            active={recording === 'active'}
            disabled={(busy && recording !== 'active') || Boolean(voice)}
            onClick={() => {
              if (stopRecording.current) {
                stopRecording.current();
              } else {
                void startRecording();
              }
            }}
          />
          <Button
            className={styles.send}
            type="submit"
            variant="primary"
            icon={<Send size={18} />}
            disabled={busy || (!question.trim() && !files.length && !voice)}
          >
            Спросить
          </Button>
        </div>
      </form>
    </section>
  );
};
