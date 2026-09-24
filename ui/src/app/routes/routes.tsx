import { Navigate, type RouteObject } from 'react-router';
import { AccessPage } from '@/pages/access';
import { AccountPage } from '@/pages/account';
import { CasePage } from '@/pages/case';
import { ConnectPage } from '@/pages/connect';
import { LoginPage } from '@/pages/login';
import { MovingPage } from '@/pages/moving';
import { PeoplePage } from '@/pages/people';
import { ProjectPage } from '@/pages/project';
import { QuestionsPage } from '@/pages/questions';
import { TaskPage } from '@/pages/task';
import { TasksPage } from '@/pages/tasks';
import { AppShell } from '../layouts/app-shell';
import { NotFound } from './not-found';
import { RequireAuth } from './require-auth';
import { RequireSignInMode } from './require-sign-in-mode';

/**
 * Маршруты списком, а не готовым роутером: тот же список поднимают страничные тесты
 * в памяти, поэтому проверяется настоящая навигация, а не её пересказ.
 */
export const routes: RouteObject[] = [
  { path: '/login', element: <LoginPage /> },
  {
    element: <RequireAuth />,
    children: [
      {
        element: <AppShell />,
        children: [
          { index: true, element: <Navigate to="/tasks" replace /> },
          { path: 'questions', element: <QuestionsPage /> },
          { path: 'connect', element: <ConnectPage /> },
          { path: 'access', element: <AccessPage /> },
          { path: 'moving', element: <MovingPage /> },
          {
            element: <RequireSignInMode />,
            children: [
              { path: 'account', element: <AccountPage /> },
              { path: 'people', element: <PeoplePage /> },
            ],
          },
          { path: 'tasks', element: <TasksPage /> },
          { path: 'tasks/:key', element: <TaskPage /> },
          { path: 'tasks/:key/case', element: <CasePage /> },
          { path: 'projects/:key', element: <ProjectPage /> },
          { path: '*', element: <NotFound /> },
        ],
      },
    ],
  },
];
