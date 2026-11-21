import { Navigate, Outlet } from 'react-router';

import { useIsAuthenticated } from '@/entities/session';
import { routePaths } from '@/shared/config';

/** Пускает дальше только авторизованных; при потере сессии возвращает на вход. */
export const RequireAuth = () => {
  const authenticated = useIsAuthenticated();
  return authenticated ? <Outlet /> : <Navigate to={routePaths.login} replace />;
};

/** Страница входа не нужна тем, кто уже вошёл. */
export const GuestOnly = () => {
  const authenticated = useIsAuthenticated();
  return authenticated ? <Navigate to={routePaths.root} replace /> : <Outlet />;
};
