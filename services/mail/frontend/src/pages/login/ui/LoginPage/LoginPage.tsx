import { useNavigate } from 'react-router';

import { AuthForm } from '@/features/auth-form';
import { routePaths } from '@/shared/config';
import { Logo } from '@/shared/ui';

import styles from './LoginPage.module.css';

export const LoginPage = () => {
  const navigate = useNavigate();
  return (
    <main className={styles.page}>
      <Logo size="lg" caption="Почта" />
      <AuthForm
        onAuthenticated={() => {
          void navigate(routePaths.root, { replace: true });
        }}
      />
    </main>
  );
};
