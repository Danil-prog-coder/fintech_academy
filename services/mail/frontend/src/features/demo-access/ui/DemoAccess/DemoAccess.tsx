import { GraduationCap } from 'lucide-react';
import { useState } from 'react';

import { useDemoLoginMutation, useGetDemoInfoQuery } from '@/entities/session';
import { getErrorMessage } from '@/shared/api';
import { saveTokens } from '@/shared/lib/tokens';
import { Button, Notice } from '@/shared/ui';

import styles from './DemoAccess.module.css';

interface DemoAccessProps {
  onAuthenticated: () => void;
}

/**
 * Кнопка тестового доступа на странице входа: вход в готовый демо-аккаунт без регистрации.
 * Показывается, только если тестовый доступ включён на сервере (DEMO_ENABLED).
 */
export const DemoAccess = ({ onAuthenticated }: DemoAccessProps) => {
  const { data: info } = useGetDemoInfoQuery(undefined);
  const [demoLogin, { isLoading }] = useDemoLoginMutation();
  const [error, setError] = useState<string | null>(null);

  if (!info?.enabled) {
    return null;
  }

  const enter = async () => {
    setError(null);
    try {
      saveTokens(await demoLogin(undefined).unwrap());
      onAuthenticated();
    } catch (cause) {
      setError(getErrorMessage(cause));
    }
  };

  return (
    <section className={styles.card} aria-label="Тестовый доступ">
      <Button
        variant="primary"
        size="lg"
        fullWidth
        className={styles.button}
        icon={<GraduationCap size={22} />}
        disabled={isLoading}
        onClick={() => void enter()}
      >
        {isLoading ? 'Входим…' : info.label}
      </Button>
      <p className={styles.hint}>
        Без регистрации: почтовый ящик и проект с базой знаний уже подключены, при первом входе
        покажем короткий тур.
      </p>
      {error ? <Notice tone="danger">{error}</Notice> : null}
    </section>
  );
};
