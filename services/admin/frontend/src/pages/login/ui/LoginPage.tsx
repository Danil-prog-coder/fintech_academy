import { LogIn } from 'lucide-react';
import { useState } from 'react';
import { useNavigate } from 'react-router';

import { useLoginMutation } from '@/entities/session';
import { getErrorMessage } from '@/shared/api';
import { routePaths } from '@/shared/config';
import { Button, Card, layout, Logo, Notice, TextField } from '@/shared/ui';

/** Вход: логин, пароль и код проекта (код выдаётся владельцу при создании проекта). */
export const LoginPage = () => {
  const [login, setLogin] = useState('');
  const [password, setPassword] = useState('');
  const [code, setCode] = useState('');
  const [doLogin, { isLoading, error }] = useLoginMutation();
  const navigate = useNavigate();

  return (
    <div className={layout.center}>
      <div className={layout.narrow}>
        <Card>
          <Logo caption="Панель проекта" />
          <form
            className={layout.stack}
            onSubmit={(event) => {
              event.preventDefault();
              void doLogin({ login: login.trim(), password, project_code: code.trim() })
                .unwrap()
                .then((me) =>
                  navigate(me.role === 'support' ? routePaths.tickets : routePaths.root, {
                    replace: true,
                  }),
                )
                .catch(() => undefined);
            }}
          >
            <TextField
              label="Логин"
              placeholder="Логин"
              autoComplete="username"
              value={login}
              onChange={setLogin}
            />
            <TextField
              label="Пароль"
              placeholder="Пароль"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={setPassword}
            />
            <TextField
              label="Код проекта"
              placeholder="Код проекта"
              autoComplete="off"
              value={code}
              onChange={setCode}
            />
            <Button
              type="submit"
              variant="primary"
              icon={<LogIn size={18} />}
              disabled={isLoading || !login || !password || !code}
            >
              Войти
            </Button>
          </form>
          {error ? <Notice tone="danger">{getErrorMessage(error)}</Notice> : null}
          <p className={layout.muted}>
            Код проекта знает владелец. Если вы ещё не задали пароль — откройте ссылку, которую
            получили при назначении статуса.
          </p>
        </Card>
      </div>
    </div>
  );
};
