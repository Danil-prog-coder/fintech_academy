import { GitBranch, KeyRound } from 'lucide-react';
import { useState } from 'react';

import { useConnectRepoMutation, type RepoStatusInfo } from '@/entities/repo';
import { getErrorCode, getErrorMessage } from '@/shared/api';
import { showToast } from '@/shared/lib/toast';
import { Button, Notice, TextField } from '@/shared/ui';

import styles from './ConnectRepoForm.module.css';

interface ConnectRepoFormProps {
  /** Текущее состояние: при reauth_required форма просит только новый токен. */
  current: RepoStatusInfo | undefined;
}

export const ConnectRepoForm = ({ current }: ConnectRepoFormProps) => {
  const reauth = current?.status === 'reauth_required' && current.url !== null;
  const [connect, { isLoading }] = useConnectRepoMutation();
  const [url, setUrl] = useState('');
  const [token, setToken] = useState('');
  const [error, setError] = useState<string | null>(null);

  const submit = async () => {
    setError(null);
    const body = {
      url: reauth ? (current.url ?? '') : url.trim(),
      github_token: token.trim() || undefined,
    };
    try {
      try {
        await connect({ ...body, replace: reauth }).unwrap();
      } catch (cause) {
        if (getErrorCode(cause) !== 'repo_exists') {
          throw cause;
        }
        if (
          !window.confirm(
            'Репозиторий уже подключён. Заменить его новым? Индекс будет построен заново.',
          )
        ) {
          return;
        }
        await connect({ ...body, replace: true }).unwrap();
      }
      setToken('');
      showToast(
        reauth ? 'Токен обновлён, индекс обновляется' : 'Репозиторий подключён, идёт индексация',
        'success',
      );
    } catch (cause) {
      setError(getErrorMessage(cause, 'Не удалось подключить репозиторий.'));
    }
  };

  return (
    <form
      className={styles.form}
      onSubmit={(event) => {
        event.preventDefault();
        void submit();
      }}
    >
      {reauth ? (
        <Notice tone="warning" title="GitHub отозвал доступ" compact>
          Введите новый токен для {current.owner}/{current.name}. Ответы пока строятся по прежнему
          индексу.
        </Notice>
      ) : (
        <TextField
          label="Адрес репозитория"
          placeholder="https://github.com/owner/name"
          required
          size="lg"
          icon={<GitBranch size={20} />}
          value={url}
          onChange={setUrl}
        />
      )}
      <TextField
        label="GitHub-токен"
        type="password"
        placeholder={reauth ? 'Новый токен (PAT)' : 'Токен GitHub — для приватных репозиториев'}
        autoComplete="off"
        required={reauth}
        size="lg"
        icon={<KeyRound size={20} />}
        value={token}
        onChange={setToken}
      />
      <p className={styles.hint}>
        Токен (PAT) нужен для приватных репозиториев и для автоматического создания вебхука.
        Хранится на сервере в зашифрованном виде.
      </p>
      {error ? <Notice tone="danger">{error}</Notice> : null}
      <Button type="submit" variant="primary" size="lg" disabled={isLoading}>
        {isLoading ? 'Подключаем…' : reauth ? 'Обновить токен' : 'Подключить репозиторий'}
      </Button>
    </form>
  );
};
