import { useNavigate } from 'react-router';

import { AuthForm } from '@/features/auth-form';
import { DemoAccess } from '@/features/demo-access';
import { routePaths } from '@/shared/config';
import { Logo } from '@/shared/ui';

import styles from './LoginPage.module.css';

export const LoginPage = () => {
  const navigate = useNavigate();
  const enter = () => {
    void navigate(routePaths.root, { replace: true });
  };
  return (
    <main className={styles.page}>
      <Logo size="lg" caption="Почта" />
      <DemoAccess onAuthenticated={enter} />
      <AuthForm onAuthenticated={enter} />
    </main>
  );
};
