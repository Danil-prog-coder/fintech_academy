import { KeyRound } from 'lucide-react';
import { useState } from 'react';
import { Link, useSearchParams } from 'react-router';

import { useSetupPasswordMutation } from '@/entities/session';
import { getErrorMessage } from '@/shared/api';
import { routePaths } from '@/shared/config';
import { Button, Card, layout, Logo, Notice, TextField } from '@/shared/ui';

/** Одноразовая ссылка: человек задаёт пароль сам, через API пароли не передаются. */
export const SetupPage = () => {
  const [params] = useSearchParams();
  const token = params.get('token') ?? '';
  const [password, setPassword] = useState('');
  const [repeat, setRepeat] = useState('');
  const [setup, { isLoading, error, data }] = useSetupPasswordMutation();
  const mismatch = repeat.length > 0 && repeat !== password;

  return (
    <div className={layout.center}>
      <div className={layout.narrow}>
        <Card>
          <Logo caption="Панель проекта" />
          {data ? (
            <Notice tone="success" title="Пароль задан">
              Ваш логин: <strong>{data.login}</strong>
              {data.project_name ? ` (проект «${data.project_name}»)` : ''}. Для входа понадобится
              ещё код проекта. <Link to={routePaths.login}>Перейти ко входу</Link>
            </Notice>
          ) : (
            <form
              className={layout.stack}
              onSubmit={(event) => {
                event.preventDefault();
                void setup({ token, password })
                  .unwrap()
                  .catch(() => undefined);
              }}
            >
              <TextField
                label="Новый пароль"
                placeholder="Новый пароль (от 10 символов)"
                type="password"
                autoComplete="new-password"
                value={password}
                onChange={setPassword}
              />
              <TextField
                label="Повторите пароль"
                placeholder="Повторите пароль"
                type="password"
                autoComplete="new-password"
                value={repeat}
                onChange={setRepeat}
              />
              {mismatch ? (
                <Notice tone="warning" compact>
                  Пароли не совпадают
                </Notice>
              ) : null}
              <Button
                type="submit"
                variant="primary"
                icon={<KeyRound size={18} />}
                disabled={isLoading || !token || password.length < 10 || mismatch || !repeat}
              >
                Сохранить пароль
              </Button>
            </form>
          )}
          {!token ? (
            <Notice tone="danger">В ссылке нет токена — откройте ссылку целиком.</Notice>
          ) : null}
          {error ? <Notice tone="danger">{getErrorMessage(error)}</Notice> : null}
        </Card>
      </div>
    </div>
  );
};
