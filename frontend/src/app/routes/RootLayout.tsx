import { Outlet } from 'react-router';

import { ToastHost } from '@/shared/ui';
import { ScreenNavigator } from '@/widgets/screen-navigator';

/** Корневой маршрут без собственной разметки: страница, уведомления и навигатор по экранам. */
export const RootLayout = () => (
  <>
    <Outlet />
    <ToastHost />
    <ScreenNavigator />
  </>
);
