import type { ReactNode } from 'react';
import { QueryClientProvider, type QueryClient } from '@tanstack/react-query';
import { SessionWatcher } from './session-watcher';

/**
 * Обвязка приложения без маршрутизатора: серверное состояние и присмотр за сеансом.
 *
 * Отдельно от `App`, чтобы страничные тесты поднимали ту же обвязку, что и живое
 * приложение: иначе `401` в тесте не приводил бы к тем же последствиям, что в браузере.
 */
export function AppProviders({
  queryClient,
  children,
}: {
  queryClient: QueryClient;
  children: ReactNode;
}) {
  return (
    <QueryClientProvider client={queryClient}>
      <SessionWatcher>{children}</SessionWatcher>
    </QueryClientProvider>
  );
}
