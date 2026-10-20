import { type RepoStatus } from '../model/types';

export const repoStatusLabel: Record<RepoStatus, string> = {
  not_connected: 'Не подключён',
  indexing: 'Идёт индексация',
  ready: 'Готов к вопросам',
  updating: 'Обновляется',
  error: 'Ошибка',
  reauth_required: 'Нужен новый токен',
};
