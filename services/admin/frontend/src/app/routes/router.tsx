import { createBrowserRouter, Navigate } from 'react-router';

import { DashboardPage } from '@/pages/dashboard';
import { DocumentsPage } from '@/pages/documents';
import { FaqPage } from '@/pages/faq';
import { LoginPage } from '@/pages/login';
import { MembersPage } from '@/pages/members';
import { ProjectsPage } from '@/pages/projects';
import { QuestionsPage } from '@/pages/questions';
import { RegisterPage } from '@/pages/register';
import { SettingsPage } from '@/pages/settings';
import { SetupPage } from '@/pages/setup';
import { TicketPage } from '@/pages/ticket';
import { TicketsPage } from '@/pages/tickets';
import { routePaths } from '@/shared/config';

import { RequireAccount, RequireRole } from './AuthGuard';
import { RootLayout } from './RootLayout';

export const router = createBrowserRouter([
  {
    element: <RootLayout />,
    children: [
      { path: routePaths.login, element: <LoginPage /> },
      { path: routePaths.register, element: <RegisterPage /> },
      { path: routePaths.setup, element: <SetupPage /> },
      {
        element: <RequireAccount />,
        children: [{ path: routePaths.projects, element: <ProjectsPage /> }],
      },
      {
        element: <RequireRole roles={['owner', 'admin']} />,
        children: [
          { path: routePaths.root, element: <DashboardPage /> },
          { path: routePaths.documents, element: <DocumentsPage /> },
          { path: routePaths.questions, element: <QuestionsPage /> },
          { path: routePaths.members, element: <MembersPage /> },
          { path: routePaths.faq, element: <FaqPage /> },
        ],
      },
      {
        element: <RequireRole roles={['owner', 'admin', 'support']} />,
        children: [
          { path: routePaths.tickets, element: <TicketsPage /> },
          { path: routePaths.ticket, element: <TicketPage /> },
        ],
      },
      {
        element: <RequireRole roles={['owner']} />,
        children: [{ path: routePaths.settings, element: <SettingsPage /> }],
      },
      { path: '*', element: <Navigate to={routePaths.root} replace /> },
    ],
  },
]);
