import { Navigate, Outlet } from 'react-router';

import { useGetMeQuery, type Role } from '@/entities/session';
import { routePaths } from '@/shared/config';
import { Spinner } from '@/shared/ui';

/** Пускает только с живой сессией аккаунта сайта (проект может быть ещё не выбран). */
export const RequireAccount = () => {
  const { data, isLoading, isError } = useGetMeQuery(undefined);
  if (isLoading) {
    return <Spinner label="Проверяем сессию" />;
  }
  if (isError || !data) {
    return <Navigate to={routePaths.login} replace />;
  }
  return <Outlet />;
};

/** Пускает в страницы проекта: нужна сессия, выбранный проект и подходящая роль. */
export const RequireRole = ({ roles }: { roles: Role[] }) => {
  const { data, isLoading, isError } = useGetMeQuery(undefined);
  if (isLoading) {
    return <Spinner label="Проверяем сессию" />;
  }
  if (isError || !data) {
    return <Navigate to={routePaths.login} replace />;
  }
  if (!data.project || !data.role) {
    return <Navigate to={routePaths.projects} replace />;
  }
  if (!roles.includes(data.role)) {
    return <Navigate to={routePaths.tickets} replace />;
  }
  return <Outlet />;
};
