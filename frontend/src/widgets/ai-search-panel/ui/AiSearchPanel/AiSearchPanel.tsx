import { skipToken } from '@reduxjs/toolkit/query';
import { Pencil, Search, X } from 'lucide-react';
import { type ReactNode, useRef } from 'react';

import { toAttachment, type DocumentFile } from '@/entities/document';
import { draftAttachmentSet, selectDraft } from '@/entities/draft';
import { letterSelected, selectSelectedLetterId } from '@/entities/letter';
import {
  caveatAccepted,
  searchPanelClosed,
  searchReset,
  searchRetried,
  searchSubmitted,
  selectCaveatAccepted,
  selectSearchOpen,
  selectSearchRequest,
  useAiSearchQuery,
  type SearchResult,
} from '@/features/ai-search';
import { useAppDispatch, useAppSelector } from '@/shared/lib/store';
import { showToast } from '@/shared/lib/toast';
import { Button, EmptyState, IconButton, Logo, Notice } from '@/shared/ui';

import styles from './AiSearchPanel.module.css';
import { DocumentResultCard } from '../DocumentResultCard/DocumentResultCard';
import { LetterResults } from '../LetterResults/LetterResults';
import { SearchForm } from '../SearchForm/SearchForm';
import { SearchProgress } from '../SearchProgress/SearchProgress';
import { SearchSources } from '../SearchSources/SearchSources';
import { VersionResults } from '../VersionResults/VersionResults';

const examples = [
  'Найти договор с подрядчиком',
  'Показать презентацию по проекту',
  'Где финансовая смета проекта?',
  'Кто согласовал презентацию?',
];

/** Самостоятельный AI-поиск в закрываемой правой панели. Письмо остаётся на месте. */
export const AiSearchPanel = () => {
  const dispatch = useAppDispatch();
  const open = useAppSelector(selectSearchOpen);
  const request = useAppSelector(selectSearchRequest);
  const caveat = useAppSelector(selectCaveatAccepted);
  const selectedLetterId = useAppSelector(selectSelectedLetterId);
  const draft = useAppSelector((state) => selectDraft(state, selectedLetterId));
  const { currentData: result, isFetching } = useAiSearchQuery(request ?? skipToken);
  const mainInputRef = useRef<HTMLInputElement>(null);

  if (!open) {
    return null;
  }

  const submit = (query: string, refine = false) => {
    dispatch(searchSubmitted({ query, refine }));
  };

  const attach = (document: DocumentFile) => {
    if (!selectedLetterId || !draft) {
      showToast('Откройте письмо, чтобы прикрепить файл к ответу', 'warning');
      return;
    }
    dispatch(
      draftAttachmentSet({
        letterId: selectedLetterId,
        attachment: toAttachment(document, {
          externalRecipient: draft.to.some((recipient) => recipient.external),
        }),
      }),
    );
    showToast(`Файл «${document.name}» прикреплён к ответу`, 'success');
  };

  const refineSection = (
    <div className={styles.refine}>
      <h3 className={styles.sectionTitle}>Уточнить поиск</h3>
      <SearchForm
        key={`refine-${String(request?.nonce ?? 0)}`}
        variant="refine"
        label="Уточнить вопрос"
        placeholder="Уточнить вопрос…"
        initialQuery=""
        onSubmit={(query) => {
          submit(query, true);
        }}
      />
      <Button
        size="lg"
        fullWidth
        icon={<Search size={20} />}
        onClick={() => {
          dispatch(searchReset());
        }}
      >
        Новый поиск
      </Button>
    </div>
  );

  const renderResult = (value: SearchResult): ReactNode => {
    switch (value.kind) {
      case 'document':
        return (
          <>
            <h3 className={styles.sectionTitle}>Результат</h3>
            <DocumentResultCard
              document={value.document}
              reason={value.reason}
              basis={value.basis}
              onAttach={attach}
            />
            {refineSection}
          </>
        );
      case 'multiple':
        return (
          <>
            <VersionResults
              items={value.items}
              note={value.note}
              onAttach={attach}
              onClarify={(document) => {
                submit(`Кто согласовал ${document.name}?`, true);
              }}
            />
            {refineSection}
          </>
        );
      case 'answer':
        return (
          <>
            <h3 className={styles.sectionTitle}>Ответ</h3>
            <p className={styles.answer}>{value.answer}</p>
            <h3 className={styles.sectionTitle}>Источники</h3>
            <SearchSources sources={value.sources} />
            {refineSection}
          </>
        );
      case 'letters':
        return (
          <LetterResults
            letters={value.letters}
            unavailableSource={value.unavailableSource}
            caveatAccepted={caveat}
            onOpen={(letter) => {
              if (letter.letterId) {
                dispatch(letterSelected(letter.letterId));
              } else {
                showToast(`Открываем письмо «${letter.subject}» с проверкой доступа`);
              }
            }}
            onRetry={() => {
              dispatch(searchRetried());
            }}
            onAcceptCaveat={() => {
              dispatch(caveatAccepted());
            }}
          />
        );
      case 'not_found':
        return (
          <>
            <EmptyState title={value.title} text={value.text} />
            <div className={styles.tips}>
              <h3 className={styles.sectionTitle}>Попробуйте уточнить запрос</h3>
              <ul className={styles.tipList}>
                <li>Укажите более конкретные формулировки</li>
                <li>Проверьте другие варианты названия проекта или документов</li>
                <li>Используйте ключевые слова из переписки</li>
              </ul>
            </div>
            <div className={styles.buttons}>
              <Button
                size="lg"
                icon={<Pencil size={18} />}
                onClick={() => {
                  mainInputRef.current?.focus();
                  mainInputRef.current?.select();
                }}
              >
                Изменить запрос
              </Button>
              <Button
                variant="primary"
                size="lg"
                icon={<Search size={18} />}
                onClick={() => {
                  dispatch(searchReset());
                }}
              >
                Новый поиск
              </Button>
            </div>
          </>
        );
    }
  };

  const partial =
    !isFetching && result?.kind === 'letters' && result.unavailableSource !== null && !caveat;

  return (
    <aside className={styles.panel} aria-label="AI-поиск">
      <header className={styles.header}>
        <span className={styles.title}>
          <Logo size="md" withText={false} />
          AI-поиск
        </span>
        <IconButton
          label="Закрыть AI-поиск"
          icon={<X size={24} />}
          onClick={() => {
            dispatch(searchPanelClosed());
          }}
        />
      </header>

      {partial ? (
        <Notice tone="caution" title="Поиск выполнен не полностью" compact>
          Один источник временно недоступен. Показаны результаты из доступных источников.
        </Notice>
      ) : (
        <p className={styles.subtitle}>Поиск по доступным вам материалам</p>
      )}

      <SearchForm
        key={`main-${String(request?.nonce ?? 0)}`}
        inputRef={mainInputRef}
        variant="main"
        label="Что найти в рабочих материалах?"
        placeholder="Что найти в рабочих материалах?"
        initialQuery={request?.query ?? ''}
        onSubmit={(query) => {
          submit(query);
        }}
      />

      <div className={styles.body}>
        {!request ? (
          <>
            <h3 className={styles.sectionTitle}>Примеры запросов</h3>
            <ul className={styles.examples}>
              {examples.map((example) => (
                <li key={example}>
                  <button
                    type="button"
                    className={styles.example}
                    onClick={() => {
                      submit(example);
                    }}
                  >
                    <Search size={18} />
                    {example}
                  </button>
                </li>
              ))}
            </ul>
            <EmptyState
              title="Введите запрос"
              text="Здесь появятся результаты из ваших писем, файлов и документов после выполнения запроса."
            />
          </>
        ) : isFetching || !result ? (
          <SearchProgress key={request.nonce} />
        ) : (
          renderResult(result)
        )}
      </div>
    </aside>
  );
};
