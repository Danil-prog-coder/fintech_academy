import { ChevronDown, ChevronUp, FileText, Mail } from 'lucide-react';
import { useState } from 'react';

import {
  ConnectButton,
  type ConnectionKind,
  type ConnectionStatus,
} from '@/features/connect-source';
import { cx } from '@/shared/lib/cx';
import { Badge, type BadgeTone } from '@/shared/ui';

import styles from './SourceConnectCard.module.css';

const statusMeta: Record<ConnectionStatus, { tone: BadgeTone; label: string }> = {
  not_connected: { tone: 'danger', label: 'Не подключено' },
  connecting: { tone: 'warning', label: 'Подключается' },
  reauthorizing: { tone: 'warning', label: 'Подключается' },
  connected: { tone: 'success', label: 'Подключено' },
  auth_required: { tone: 'warning', label: 'Нужна авторизация' },
  forbidden: { tone: 'danger', label: 'Запрещено' },
  error: { tone: 'danger', label: 'Ошибка' },
};

const content: Record<ConnectionKind, { title: string; description: string; data: string }> = {
  mail: {
    title: 'Корпоративная почта',
    description:
      'Чтение писем, анализ переписки и вложений для подготовки ответов и поиска информации.',
    data: 'Подключаются письма и переписка, к которым у вас есть доступ в организации. SOLUTIONS использует их только для поиска и подготовки ответов.',
  },
  documents: {
    title: 'Общие документы',
    description:
      'Доступ к внутренним документам вашей компании для поиска и использования информации.',
    data: 'Подключаются документы и файлы, к которым у вас есть доступ в организации. SOLUTIONS использует их только для поиска и подготовки ответов.',
  },
};

interface SourceConnectCardProps {
  kind: ConnectionKind;
  status: ConnectionStatus;
  highlighted: boolean;
}

export const SourceConnectCard = ({ kind, status, highlighted }: SourceConnectCardProps) => {
  const [expanded, setExpanded] = useState(highlighted);
  const meta = statusMeta[status];
  const text = content[kind];

  return (
    <article className={cx(styles.card, highlighted && styles.highlighted)}>
      <div className={styles.main}>
        <span className={styles.icon}>
          {kind === 'mail' ? (
            <Mail size={40} strokeWidth={1.8} />
          ) : (
            <FileText size={40} strokeWidth={1.8} />
          )}
        </span>
        <div className={styles.info}>
          <h2 className={styles.title}>{text.title}</h2>
          <Badge tone={meta.tone} dot>
            {meta.label}
          </Badge>
          <p className={styles.description}>{text.description}</p>
          <ConnectButton kind={kind} primary={highlighted} />
        </div>
      </div>
      <div className={styles.details}>
        <button
          type="button"
          className={styles.toggle}
          aria-expanded={expanded}
          onClick={() => {
            setExpanded((value) => !value);
          }}
        >
          Какие данные используются?
          {expanded ? <ChevronUp size={22} /> : <ChevronDown size={22} />}
        </button>
        {expanded ? <p className={styles.data}>{text.data}</p> : null}
      </div>
    </article>
  );
};
