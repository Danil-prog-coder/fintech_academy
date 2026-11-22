import { createBrowserRouter, Navigate } from 'react-router';

import { ChatPage } from '@/pages/chat';
import { ConnectMailboxPage } from '@/pages/connect-mailbox';
import { LoginPage } from '@/pages/login';
import { MailboxPage } from '@/pages/mailbox';
import { OverviewPage } from '@/pages/overview';
import { ProjectsPage } from '@/pages/projects';
import { routePaths } from '@/shared/config';

import { GuestOnly, RequireAuth } from './AuthGuard';
import { RootLayout } from './RootLayout';

export const router = createBrowserRouter([
  {
    element: <RootLayout />,
    children: [
      {
        element: <GuestOnly />,
        children: [{ path: routePaths.login, element: <LoginPage /> }],
      },
      {
        element: <RequireAuth />,
        children: [
          { path: routePaths.root, element: <OverviewPage /> },
          { path: routePaths.mail, element: <MailboxPage /> },
          { path: routePaths.connect, element: <ConnectMailboxPage /> },
          { path: routePaths.projects, element: <ProjectsPage /> },
          { path: routePaths.chat, element: <ChatPage /> },
        ],
      },
      { path: '*', element: <Navigate to={routePaths.root} replace /> },
    ],
  },
]);
