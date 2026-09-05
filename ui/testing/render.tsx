import { QueryClient } from '@tanstack/react-query';
import { MemoryRouter, useRoutes } from 'react-router';
import { render } from '@testing-library/react';
import { AppProviders, routes } from '@/app';

function Routed() {
  return useRoutes(routes);
}

/**
 * Поднимает приложение целиком на маршрутах в памяти: страничный тест проверяет
 * настоящую обвязку и настоящие переходы, а не отдельно взятый компонент.
 *
 * Маршрутизатор объявительный (`MemoryRouter` + `useRoutes`), а не `createMemoryRouter`:
 * тот на каждом переходе строит `Request` из недици с `AbortSignal` из jsdom, и они
 * друг друга не принимают. Список маршрутов при этом тот же самый, что у приложения.
 */
export function renderApp(initialPath = '/') {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false, staleTime: 0 },
      mutations: { retry: false },
    },
  });

  const result = render(
    <AppProviders queryClient={queryClient}>
      <MemoryRouter initialEntries={[initialPath]}>
        <Routed />
      </MemoryRouter>
    </AppProviders>,
  );

  return { ...result, queryClient };
}
