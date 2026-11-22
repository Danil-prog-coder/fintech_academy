import { Link } from 'react-router';

import { useEnterProject } from '@/entities/session';
import { AuthForm } from '@/features/site-auth';
import { routePaths } from '@/shared/config';
import { Card, layout, Logo } from '@/shared/ui';

/** Регистрация аккаунта сайта. Проект создаётся или выбирается следующим шагом. */
export const RegisterPage = () => {
  const enterProject = useEnterProject();
  return (
    <div className={layout.center}>
      <div className={layout.narrow}>
        <Card>
          <Logo caption="Регистрация" />
          <AuthForm mode="register" onDone={enterProject} />
          <p className={layout.muted}>
            Уже есть аккаунт? <Link to={routePaths.login}>Войдите</Link>
          </p>
        </Card>
      </div>
    </div>
  );
};
