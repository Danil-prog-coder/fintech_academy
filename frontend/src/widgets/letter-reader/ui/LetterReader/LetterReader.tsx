import { skipToken } from '@reduxjs/toolkit/query';
import { ChevronDown, Ellipsis, Forward, MailOpen, Reply, ReplyAll, Star } from 'lucide-react';
import { useRef } from 'react';
import { useNavigate } from 'react-router';

import {
  LetterContent,
  selectSelectedLetterId,
  selectStarredIds,
  starToggled,
  useGetLetterQuery,
} from '@/entities/letter';
import { VersionPickerModal } from '@/features/choose-attachment-version';
import { selectMailConnection, type ConnectionStatus } from '@/features/connect-source';
import { PrepareReplyButton, selectAiReply } from '@/features/prepare-reply';
import { routePaths } from '@/shared/config';
import { useAppDispatch, useAppSelector } from '@/shared/lib/store';
import { showToast } from '@/shared/lib/toast';
import { Button, DropdownMenu, EmptyState, IconButton, Notice, Skeleton } from '@/shared/ui';

import styles from './LetterReader.module.css';
import { LetterToolbar } from '../LetterToolbar/LetterToolbar';
import { ReplyComposer } from '../ReplyComposer/ReplyComposer';

const unavailableNotice = (
  status: ConnectionStatus,
): { tone: 'warning' | 'danger' | 'info'; title: string; text: string; action: string } => {
  if (status === 'auth_required' || status === 'reauthorizing') {
    return {
      tone: 'warning',
      title: 'Требуется повторная авторизация',
      text: 'AI-функции временно недоступны. Почта и сохранённые черновики работают как обычно.',
      action: 'Обновить подключение',
    };
  }
  if (status === 'forbidden') {
    return {
      tone: 'danger',
      title: 'AI-помощник недоступен',
      text: 'Подключение запрещено политикой организации. Обычная почта продолжает работать.',
      action: 'Подробнее',
    };
  }
  return {
    tone: 'info',
    title: 'AI-помощник не подключён',
    text: 'Подключите рабочую почту, чтобы готовить ответы и искать материалы с помощью AI.',
    action: 'Подключить',
  };
};

/** Открытое письмо со встроенной областью ответа. */
export const LetterReader = () => {
  const dispatch = useAppDispatch();
  const navigate = useNavigate();
  const selectedId = useAppSelector(selectSelectedLetterId);
  const mailConnection = useAppSelector(selectMailConnection);
  const starredIds = useAppSelector(selectStarredIds);
  const reply = useAppSelector((state) => selectAiReply(state, selectedId));
  const { currentData: letter } = useGetLetterQuery(selectedId ?? skipToken);
  const editorRef = useRef<HTMLTextAreaElement>(null);
  const aiAvailable = mailConnection === 'connected';

  if (!selectedId) {
    return (
      <section className={styles.reader}>
        <div className={styles.empty}>
          <EmptyState
            icon={<MailOpen size={36} strokeWidth={1.5} />}
            title="Выберите письмо"
            text="Откройте письмо из списка, чтобы прочитать его и подготовить ответ."
          />
        </div>
      </section>
    );
  }

  if (!letter) {
    return (
      <section className={styles.reader}>
        <div className={styles.scroll}>
          <Skeleton width="60%" height={28} />
          <Skeleton width="40%" height={16} />
          <Skeleton width="90%" />
          <Skeleton width="80%" />
        </div>
      </section>
    );
  }

  const starred = starredIds.includes(letter.id);
  const notice = aiAvailable ? null : unavailableNotice(mailConnection);
  const focusEditor = () => {
    editorRef.current?.focus();
  };

  return (
    <section className={styles.reader} aria-label="Письмо">
      <LetterToolbar letterId={letter.id} />
      <div className={styles.scroll}>
        <LetterContent
          letter={letter}
          actions={
            <>
              <IconButton
                label={starred ? 'Снять отметку' : 'Отметить'}
                icon={<Star size={22} fill={starred ? 'currentColor' : 'none'} />}
                active={starred}
                onClick={() => {
                  dispatch(starToggled(letter.id));
                }}
              />
              <IconButton label="Ответить" icon={<Reply size={22} />} onClick={focusEditor} />
              <IconButton
                label="Ещё"
                icon={<Ellipsis size={22} />}
                onClick={() => {
                  showToast('Меню письма — функция почтового клиента (демо)');
                }}
              />
            </>
          }
        />

        {notice ? (
          <Notice
            tone={notice.tone}
            title={notice.title}
            action={
              <Button
                size="sm"
                onClick={() => {
                  void navigate(routePaths.connect);
                }}
              >
                {notice.action}
              </Button>
            }
          >
            {notice.text}
          </Notice>
        ) : null}

        {reply.status === 'idle' ? (
          <div className={styles.actions}>
            <PrepareReplyButton letterId={letter.id} disabled={!aiAvailable} />
            <div className={styles.replyGroup}>
              <Button
                size="lg"
                icon={<Reply size={20} />}
                className={styles.replyButton}
                onClick={focusEditor}
              >
                Ответить
              </Button>
              <DropdownMenu
                label="Другие варианты ответа"
                triggerClassName={styles.replyMenu}
                trigger={<ChevronDown size={18} />}
                items={[
                  {
                    id: 'reply-all',
                    label: 'Ответить всем',
                    icon: <ReplyAll size={16} />,
                    onSelect: focusEditor,
                  },
                  {
                    id: 'forward',
                    label: 'Переслать',
                    icon: <Forward size={16} />,
                    onSelect: () => {
                      showToast('Пересылка — функция почтового клиента (демо)');
                    },
                  },
                ]}
              />
            </div>
          </div>
        ) : null}

        <ReplyComposer
          key={letter.id}
          letter={letter}
          editorRef={editorRef}
          aiAvailable={aiAvailable}
        />
      </div>
      <VersionPickerModal />
    </section>
  );
};
