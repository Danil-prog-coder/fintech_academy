import { Badge, Notice, type BadgeTone } from '@/shared/ui';

import styles from './RepoStatusCard.module.css';
import { repoStatusLabel } from '../../lib/statusLabels';
import { type RepoStatus, type RepoStatusInfo } from '../../model/types';

const tones: Record<RepoStatus, BadgeTone> = {
  not_connected: 'neutral',
  indexing: 'info',
  ready: 'success',
  updating: 'info',
  error: 'danger',
  reauth_required: 'warning',
};

interface RepoStatusCardProps {
  info: RepoStatusInfo;
}

const shortCommit = (sha: string) => sha.slice(0, 7);

/** Состояние репозитория: статус, коммит, число файлов, ошибка и подсказка про вебхук. */
export const RepoStatusCard = ({ info }: RepoStatusCardProps) => (
  <div className={styles.card}>
    <div className={styles.head}>
      <Badge tone={tones[info.status]} dot>
        {repoStatusLabel[info.status]}
      </Badge>
      {info.url ? (
        <a className={styles.link} href={info.url} target="_blank" rel="noreferrer noopener">
          {info.owner}/{info.name}
        </a>
      ) : null}
    </div>
    {info.status !== 'not_connected' ? (
      <dl className={styles.facts}>
        <div>
          <dt>Последний коммит</dt>
          <dd>{info.last_commit ? shortCommit(info.last_commit) : '—'}</dd>
        </div>
        <div>
          <dt>Проиндексировано файлов</dt>
          <dd>{info.indexed_files}</dd>
        </div>
        <div>
          <dt>Пропущено файлов</dt>
          <dd>{info.skipped_files}</dd>
        </div>
        <div>
          <dt>Вебхук</dt>
          <dd>{info.webhook_registered ? 'зарегистрирован' : 'не создан'}</dd>
        </div>
      </dl>
    ) : null}
    {info.last_error ? (
      <Notice tone="danger" title="Последняя ошибка" compact>
        {info.last_error}
      </Notice>
    ) : null}
    {info.webhook_hint ? (
      <Notice tone="warning" title="Настройте вебхук вручную" compact>
        {info.webhook_hint}
      </Notice>
    ) : null}
  </div>
);
