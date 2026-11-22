import { Outlet } from 'react-router';

import { ToastHost } from '@/shared/ui';

export const RootLayout = () => (
  <>
    <Outlet />
    <ToastHost />
  </>
);
