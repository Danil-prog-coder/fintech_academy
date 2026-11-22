import { Outlet } from 'react-router';

import { ToastHost } from '@/shared/ui';

/** Корневой маршрут без собственной разметки: страница и уведомления. */
export const RootLayout = () => (
  <>
    <Outlet />
    <ToastHost />
  </>
);
