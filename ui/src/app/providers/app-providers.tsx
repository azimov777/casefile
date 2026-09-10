import type { ReactNode } from 'react';
import { QueryClientProvider, type QueryClient } from '@tanstack/react-query';
import { ErrorBoundary } from './error-boundary';
import { I18nProvider } from './i18n-provider';
import { SessionWatcher } from './session-watcher';

/**
 * Обвязка приложения без маршрутизатора: язык, граница ошибок, серверное состояние
 * и присмотр за сеансом.
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
    // Язык снаружи границы ошибок: объяснение упавшего экрана человек читает на своём
    // языке, а не на языке разработки. Бросить провайдер языка не может — он только
    // раздаёт готовый экземпляр, — поэтому роль границы от этого не страдает.
    <I18nProvider>
      {/* Граница снаружи остальных провайдеров: падение самого провайдера тоже должно
          показывать экран с объяснением, а не белый. */}
      <ErrorBoundary>
        <QueryClientProvider client={queryClient}>
          <SessionWatcher>{children}</SessionWatcher>
        </QueryClientProvider>
      </ErrorBoundary>
    </I18nProvider>
  );
}
