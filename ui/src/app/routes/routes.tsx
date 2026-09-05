import { Navigate, type RouteObject } from 'react-router';
import { LoginPage } from '@/pages/login';
import { TasksPage } from '@/pages/tasks';
import { AppShell } from '../layouts/app-shell';
import { NotFound } from './not-found';
import { RequireAuth } from './require-auth';

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
          { path: 'tasks', element: <TasksPage /> },
          { path: '*', element: <NotFound /> },
        ],
      },
    ],
  },
];
