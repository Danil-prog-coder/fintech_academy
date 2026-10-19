import {
  ChevronDown,
  CircleX,
  Ellipsis,
  EllipsisVertical,
  Forward,
  Image,
  Maximize2,
  Paperclip,
  Reply,
  ReplyAll,
  Sticker,
  Trash,
  TriangleAlert,
  Type,
  X,
} from 'lucide-react';
import { useEffect, useRef, type RefObject } from 'react';

import { getDocumentById, toAttachment } from '@/entities/document';
import {
  draftAttachmentRemoved,
  draftAttachmentSet,
  draftDiscarded,
  draftEnsured,
  draftRecipientRemoved,
  draftTextChanged,
  selectDraft,
} from '@/entities/draft';
import { type Letter } from '@/entities/letter';
import { versionPickerOpened } from '@/features/choose-attachment-version';
import {
  aiReplyReset,
  panelCollapsedChanged,
  PreparingProgress,
  scenarioContent,
  selectAiReply,
  selectPanelCollapsed,
  type ReplyScenario,
} from '@/features/prepare-reply';
import { refineCleared, selectRefine } from '@/features/refine-reply';
import { cx } from '@/shared/lib/cx';
import { useAppDispatch, useAppSelector } from '@/shared/lib/store';
import { showToast } from '@/shared/lib/toast';
import {
  Badge,
  Button,
  DropdownMenu,
  HighlightTextarea,
  IconButton,
  Logo,
  Skeleton,
} from '@/shared/ui';

import styles from './ReplyComposer.module.css';
import { useDraftAutosave } from '../../lib/useDraftAutosave';
import { AiCheckPanel } from '../AiCheckPanel/AiCheckPanel';
import { AttachmentCard } from '../AttachmentCard/AttachmentCard';
import { EditorToolbar } from '../EditorToolbar/EditorToolbar';

const BUDGET_SCENARIOS: readonly ReplyScenario[] = ['complete', 'partial', 'facts'];

const notifyMailClient = (label: string) => () => {
  showToast(`${label} — функция почтового клиента (демо)`);
};

interface ReplyComposerProps {
  letter: Letter;
  editorRef: RefObject<HTMLTextAreaElement | null>;
  aiAvailable: boolean;
}

/** Обычный редактор ответа. AI заполняет его черновиком, но отправляет письмо только пользователь. */
export const ReplyComposer = ({ letter, editorRef, aiAvailable }: ReplyComposerProps) => {
  const dispatch = useAppDispatch();
  const letterId = letter.id;
  const draft = useAppSelector((state) => selectDraft(state, letterId));
  const reply = useAppSelector((state) => selectAiReply(state, letterId));
  const refine = useAppSelector((state) => selectRefine(state, letterId));
  const panelCollapsed = useAppSelector(selectPanelCollapsed);
  const refineInputRef = useRef<HTMLInputElement>(null);

  useDraftAutosave(draft);

  useEffect(() => {
    dispatch(
      draftEnsured({
        letterId: letter.id,
        to: [
          {
            name: letter.from.name,
            email: letter.from.email,
            external: Boolean(letter.from.external),
          },
        ],
      }),
    );
  }, [dispatch, letter]);

  if (!draft) {
    return null;
  }

  const { scenario } = reply;
  const preparing = reply.status === 'preparing';
  const hasAiResult = reply.status === 'ready' || reply.status === 'error';
  const panelAvailable = aiAvailable && hasAiResult && scenario !== 'blocked';
  const showPanel = panelAvailable && !panelCollapsed;
  const content =
    reply.status === 'ready' && scenario && scenario !== 'error' ? scenarioContent[scenario] : null;
  const highlights = content?.highlights ?? [];
  const budgetWarning =
    refine.status === 'done' &&
    scenario !== null &&
    BUDGET_SCENARIOS.includes(scenario) &&
    draft.text.toLowerCase().includes('бюджет');
  const blocked = draft.attachment?.blocked ?? false;
  const canSend = Boolean(draft.text.trim()) && draft.to.length > 0 && !blocked && !preparing;
  const suggestedDocument =
    !draft.attachment && content?.attachmentId ? getDocumentById(content.attachmentId) : undefined;
  const externalRecipient = draft.to.some((recipient) => recipient.external);

  const resetReply = () => {
    dispatch(draftDiscarded({ letterId }));
    dispatch(aiReplyReset({ letterId }));
    dispatch(refineCleared({ letterId }));
  };

  const saveLabel =
    draft.saveState === 'saving'
      ? 'Черновик сохраняется…'
      : draft.savedAt
        ? `Черновик сохранён в ${draft.savedAt}`
        : null;

  return (
    <section className={styles.composer} aria-label="Ответ на письмо">
      <header className={styles.header}>
        <Reply size={20} />
        <DropdownMenu
          label="Тип ответа"
          align="left"
          trigger={
            <span className={styles.replyType}>
              Ответить <ChevronDown size={16} />
            </span>
          }
          items={[
            {
              id: 'reply-all',
              label: 'Ответить всем',
              icon: <ReplyAll size={16} />,
              onSelect: notifyMailClient('Ответить всем'),
            },
            {
              id: 'forward',
              label: 'Переслать',
              icon: <Forward size={16} />,
              onSelect: notifyMailClient('Пересылка'),
            },
          ]}
        />
        <div className={styles.headerRight}>
          {panelAvailable && panelCollapsed ? (
            <button
              type="button"
              className={styles.reopen}
              onClick={() => {
                dispatch(panelCollapsedChanged(false));
              }}
            >
              <Logo size="sm" caption="Проверка ответа" />
              <ChevronDown size={16} />
            </button>
          ) : null}
          {saveLabel ? <span className={styles.saved}>{saveLabel}</span> : null}
          <IconButton
            size="sm"
            label="Удалить черновик"
            icon={<Trash size={18} />}
            disabled={preparing}
            onClick={() => {
              resetReply();
              showToast('Черновик удалён');
            }}
          />
          <IconButton
            size="sm"
            label="Развернуть"
            icon={<Maximize2 size={18} />}
            onClick={notifyMailClient('Полноэкранный режим')}
          />
        </div>
      </header>

      <div className={styles.recipients}>
        <span className={styles.recipientsLabel}>Кому:</span>
        {draft.to.map((recipient) => (
          <span key={recipient.email} className={styles.recipient}>
            {recipient.name} &lt;{recipient.email}&gt;
            <button
              type="button"
              className={styles.removeRecipient}
              aria-label={`Удалить получателя ${recipient.name}`}
              onClick={() => {
                dispatch(draftRecipientRemoved({ letterId, email: recipient.email }));
              }}
            >
              <X size={14} />
            </button>
          </span>
        ))}
        {externalRecipient ? (
          <Badge tone="danger" icon={<CircleX size={14} />}>
            Внешний адресат
          </Badge>
        ) : null}
        <span className={styles.copies}>
          <button type="button" className={styles.copy} onClick={notifyMailClient('Копия')}>
            Копия
          </button>
          <button type="button" className={styles.copy} onClick={notifyMailClient('Скрытая копия')}>
            Скрытая копия
          </button>
        </span>
      </div>

      <div className={cx(styles.body, showPanel && styles.withPanel)}>
        <div className={styles.main}>
          {preparing ? (
            <>
              <PreparingProgress letterId={letterId} />
              <EditorToolbar />
              <div className={styles.skeleton} aria-hidden="true">
                <Skeleton width="92%" />
                <Skeleton width="70%" />
                <Skeleton width="48%" />
              </div>
            </>
          ) : (
            <>
              {budgetWarning ? (
                <div className={styles.warningBanner} role="status">
                  <TriangleAlert size={20} />
                  Сумма бюджета не подтверждена.
                </div>
              ) : null}
              <HighlightTextarea
                ref={editorRef}
                label="Текст ответа"
                placeholder="Напишите ответ…"
                value={draft.text}
                highlights={highlights}
                onChange={(text) => {
                  dispatch(draftTextChanged({ letterId, text }));
                }}
              />
              <EditorToolbar />
            </>
          )}

          {draft.attachment ? (
            <AttachmentCard
              attachment={draft.attachment}
              onOpen={() => {
                showToast(`Открываем «${draft.attachment?.name ?? ''}» с проверкой доступа`);
              }}
              onReplace={() => {
                if (draft.attachment?.documentId.startsWith('doc-pres')) {
                  dispatch(versionPickerOpened(letterId));
                } else {
                  showToast('Других версий этого файла не найдено');
                }
              }}
              onExclude={() => {
                dispatch(draftAttachmentRemoved({ letterId }));
                showToast('Файл исключён из ответа');
              }}
              onShowRule={() => {
                showToast(
                  'Правило «Передача данных AI»: только внутри компании. Изменить его может специалист ИБ.',
                  'warning',
                );
              }}
            />
          ) : null}

          {suggestedDocument && !preparing ? (
            <p className={styles.excluded}>
              Предложенный файл {suggestedDocument.name} исключён.{' '}
              <Button
                variant="link"
                onClick={() => {
                  dispatch(
                    draftAttachmentSet({
                      letterId,
                      attachment: toAttachment(suggestedDocument, { externalRecipient }),
                    }),
                  );
                }}
              >
                Вернуть
              </Button>
            </p>
          ) : null}
        </div>

        {showPanel ? (
          <AiCheckPanel
            letterId={letterId}
            reply={reply}
            editorRef={editorRef}
            refineInputRef={refineInputRef}
          />
        ) : null}
      </div>

      <footer className={styles.footer}>
        <div className={styles.sendGroup}>
          <Button
            variant="primary"
            size="lg"
            className={styles.send}
            disabled={!canSend}
            onClick={() => {
              const names = draft.to.map((recipient) => recipient.name).join(', ');
              resetReply();
              showToast(`Письмо отправлено: ${names}`, 'success');
            }}
          >
            Отправить
          </Button>
          <IconButton
            className={styles.sendMenu}
            label="Параметры отправки"
            icon={<ChevronDown size={18} />}
            disabled={!canSend}
            onClick={notifyMailClient('Отложенная отправка')}
          />
        </div>
        <IconButton
          label="Прикрепить файл"
          icon={<Paperclip size={20} />}
          disabled={blocked}
          onClick={() => {
            dispatch(versionPickerOpened(letterId));
          }}
        />
        <IconButton
          label="Изображение"
          icon={<Image size={20} />}
          onClick={notifyMailClient('Вставка изображения')}
        />
        <IconButton
          label="Эмодзи"
          icon={<Sticker size={20} />}
          onClick={notifyMailClient('Эмодзи')}
        />
        <IconButton
          label="Оформление"
          icon={<Type size={20} />}
          onClick={notifyMailClient('Оформление')}
        />
        <DropdownMenu
          label="Ещё"
          trigger={<Ellipsis size={20} />}
          triggerClassName={styles.moreTrigger}
          items={[
            {
              id: 'collapse',
              label: panelCollapsed ? 'Показать проверку AI' : 'Скрыть проверку AI',
              icon: <EllipsisVertical size={16} />,
              onSelect: () => {
                dispatch(panelCollapsedChanged(!panelCollapsed));
              },
            },
          ]}
        />
        <span className={styles.footerHint}>
          {blocked
            ? 'Продолжите после исключения запрещённого файла'
            : draft.savedAt
              ? `Сохранено в ${draft.savedAt}`
              : null}
        </span>
      </footer>
    </section>
  );
};
