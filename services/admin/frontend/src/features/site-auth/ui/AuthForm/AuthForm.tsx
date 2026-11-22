import { LogIn, UserPlus } from 'lucide-react';
import { useState } from 'react';

import { useLoginMutation, useRegisterMutation, type Me } from '@/entities/session';
import { getErrorMessage } from '@/shared/api';
import { Button, layout, Notice, TextField } from '@/shared/ui';

interface AuthFormProps {
  mode: 'login' | 'register';
  defaultLogin?: string;
  onDone: (me: Me) => void;
}

/** Вход в аккаунт сайта или регистрация: логин и пароль. Проект выбирается уже после входа. */
export const AuthForm = ({ mode, defaultLogin = '', onDone }: AuthFormProps) => {
  const [login, setLogin] = useState(defaultLogin);
  const [password, setPassword] = useState('');
  const [repeat, setRepeat] = useState('');
  const [doLogin, loginState] = useLoginMutation();
  const [doRegister, registerState] = useRegisterMutation();
  const isRegister = mode === 'register';
  const { isLoading, error } = isRegister ? registerState : loginState;
  const mismatch = isRegister && repeat.length > 0 && repeat !== password;
  const ready = isRegister
    ? login.trim().length >= 3 && password.length > 0 && repeat === password
    : Boolean(login.trim() && password);

  return (
    <form
      className={layout.stack}
      onSubmit={(event) => {
        event.preventDefault();
        const body = { login: login.trim(), password };
        void (isRegister ? doRegister(body) : doLogin(body))
          .unwrap()
          .then(onDone)
          .catch(() => undefined);
      }}
    >
      <TextField
        label="Логин"
        placeholder={isRegister ? 'Логин (латиница, цифры, . _ @ -)' : 'Логин'}
        autoComplete="username"
        autoFocus={!defaultLogin}
        value={login}
        onChange={setLogin}
      />
      <TextField
        label="Пароль"
        placeholder="Пароль"
        type="password"
        autoComplete={isRegister ? 'new-password' : 'current-password'}
        autoFocus={Boolean(defaultLogin)}
        value={password}
        onChange={setPassword}
      />
      {isRegister ? (
        <TextField
          label="Повторите пароль"
          placeholder="Повторите пароль"
          type="password"
          autoComplete="new-password"
          value={repeat}
          onChange={setRepeat}
        />
      ) : null}
      {mismatch ? (
        <Notice tone="warning" compact>
          Пароли не совпадают
        </Notice>
      ) : null}
      <Button
        type="submit"
        variant="primary"
        icon={isRegister ? <UserPlus size={18} /> : <LogIn size={18} />}
        disabled={isLoading || !ready}
      >
        {isRegister ? 'Зарегистрироваться' : 'Войти'}
      </Button>
      {error ? <Notice tone="danger">{getErrorMessage(error)}</Notice> : null}
    </form>
  );
};
