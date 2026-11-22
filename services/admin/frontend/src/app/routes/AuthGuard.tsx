import { Navigate, Outlet } from 'react-router';

import { useGetMeQuery, type Role } from '@/entities/session';
import { routePaths } from '@/shared/config';
import { Spinner } from '@/shared/ui';

/** Пускает дальше только с живой сессией и нужной ролью; поддержка без прав попадает к обращениям. */
export const RequireRole = ({ roles }: { roles: Role[] }) => {
  const { data, isLoading, isError } = useGetMeQuery(undefined);
  if (isLoading) {
    return <Spinner label="Проверяем сессию" />;
  }
  if (isError || !data) {
    return <Navigate to={routePaths.login} replace />;
  }
  if (!roles.includes(data.role)) {
    return <Navigate to={routePaths.tickets} replace />;
  }
  return <Outlet />;
};
