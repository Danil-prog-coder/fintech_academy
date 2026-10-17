import { createBrowserRouter, Navigate } from 'react-router';

import { ConnectPage } from '@/pages/connect';
import { MailPage } from '@/pages/mail';
import { routePaths } from '@/shared/config';

import { RootLayout } from './RootLayout';

export const router = createBrowserRouter([
  {
    element: <RootLayout />,
    children: [
      { path: routePaths.root, element: <Navigate to={routePaths.connect} replace /> },
      { path: routePaths.connect, element: <ConnectPage /> },
      { path: routePaths.mail, element: <MailPage /> },
      // Кабинет администратора загружается отдельным чанком.
      {
        path: routePaths.admin,
        lazy: async () => ({ Component: (await import('@/pages/overview')).OverviewPage }),
      },
      {
        path: routePaths.adminEmployees,
        lazy: async () => ({ Component: (await import('@/pages/employees')).EmployeesPage }),
      },
      {
        path: routePaths.adminSources,
        lazy: async () => ({ Component: (await import('@/pages/sources')).SourcesPage }),
      },
      {
        path: routePaths.adminSecurity,
        lazy: async () => ({ Component: (await import('@/pages/security')).SecurityPage }),
      },
      {
        path: routePaths.adminOrganization,
        lazy: async () => ({
          Component: (await import('@/pages/organization')).OrganizationPage,
        }),
      },
      { path: '*', element: <Navigate to={routePaths.root} replace /> },
    ],
  },
]);
