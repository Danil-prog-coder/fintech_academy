import { Link } from 'react-router';

import { useEnterProject } from '@/entities/session';
import { AuthForm } from '@/features/site-auth';
import { routePaths } from '@/shared/config';
import { Card, layout, Logo } from '@/shared/ui';

/** Вход: логин и пароль аккаунта сайта. Дальше — свой проект или выбор проекта. */
export const LoginPage = () => {
  const enterProject = useEnterProject();
  return (
    <div className={layout.center}>
      <div className={layout.narrow}>
        <Card>
          <Logo caption="Панель проекта" />
          <AuthForm mode="login" onDone={enterProject} />
          <p className={layout.muted}>
            Нет аккаунта? <Link to={routePaths.register}>Зарегистрируйтесь</Link> — после этого
            можно создать проект или войти в чужой как админ по коду проекта.
          </p>
        </Card>
      </div>
    </div>
  );
};
