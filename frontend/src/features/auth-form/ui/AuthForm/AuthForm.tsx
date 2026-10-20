import { LogIn, UserPlus } from 'lucide-react';
import { useState } from 'react';

import { useLoginMutation, useRegisterMutation } from '@/entities/session';
import { getErrorMessage } from '@/shared/api';
import { saveTokens } from '@/shared/lib/tokens';
import { Button, Notice, TextField } from '@/shared/ui';

import styles from './AuthForm.module.css';

type Mode = 'login' | 'register';

interface AuthFormProps {
  onAuthenticated: () => void;
}

const MIN_PASSWORD = 8;

export const AuthForm = ({ onAuthenticated }: AuthFormProps) => {
  const [mode, setMode] = useState<Mode>('login');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [login, loginState] = useLoginMutation();
  const [register, registerState] = useRegisterMutation();
  const pending = loginState.isLoading || registerState.isLoading;
  const isLogin = mode === 'login';

  const submit = async () => {
    setError(null);
    if (!isLogin && password.length < MIN_PASSWORD) {
      setError(`Пароль должен быть не короче ${String(MIN_PASSWORD)} символов.`);
      return;
    }
    try {
      const credentials = { email: email.trim(), password };
      const tokens = await (isLogin ? login(credentials) : register(credentials)).unwrap();
      saveTokens(tokens);
      onAuthenticated();
    } catch (cause) {
      setError(getErrorMessage(cause));
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
      <h1 className={styles.title}>{isLogin ? 'Вход' : 'Регистрация'}</h1>
      <TextField
        label="Email"
        type="email"
        placeholder="Email"
        autoComplete="email"
        required
        size="lg"
        value={email}
        onChange={setEmail}
      />
      <TextField
        label="Пароль"
        type="password"
        placeholder="Пароль"
        autoComplete={isLogin ? 'current-password' : 'new-password'}
        required
        size="lg"
        value={password}
        onChange={setPassword}
      />
      {error ? <Notice tone="danger">{error}</Notice> : null}
      <Button
        type="submit"
        variant="primary"
        size="lg"
        fullWidth
        disabled={pending}
        icon={isLogin ? <LogIn size={20} /> : <UserPlus size={20} />}
      >
        {isLogin ? 'Войти' : 'Создать аккаунт'}
      </Button>
      <Button
        variant="link"
        onClick={() => {
          setMode(isLogin ? 'register' : 'login');
          setError(null);
        }}
      >
        {isLogin ? 'Нет аккаунта? Зарегистрироваться' : 'Уже есть аккаунт? Войти'}
      </Button>
    </form>
  );
};
