import { useEffect } from 'react';
import { QueryClient } from '@tanstack/react-query';
import { MemoryRouter, useLocation, useRoutes } from 'react-router';
import { render } from '@testing-library/react';
import { AppProviders, routes } from '@/app';
import { i18n, type Language } from '@/shared/i18n';

function Routed() {
  return useRoutes(routes);
}

/**
 * Текущий адрес маршрутизатора в памяти.
 *
 * `MemoryRouter` не трогает `window.location`, поэтому «а поменялся ли адрес» иначе
 * из теста не видно вовсе — а часть состояния экрана живёт именно в адресе
 * (`CONVENTIONS.md`, «Состояние»), и проверять её надо.
 */
export const address = { current: '/' };

function AddressProbe() {
  const location = useLocation();
  useEffect(() => {
    address.current = `${location.pathname}${location.search}`;
  }, [location]);
  return null;
}

/**
 * Поднимает приложение целиком на маршрутах в памяти: страничный тест проверяет
 * настоящую обвязку и настоящие переходы, а не отдельно взятый компонент.
 *
 * Маршрутизатор объявительный (`MemoryRouter` + `useRoutes`), а не `createMemoryRouter`:
 * тот на каждом переходе строит `Request` из недици с `AbortSignal` из jsdom, и они
 * друг друга не принимают. Список маршрутов при этом тот же самый, что у приложения.
 */
export function renderApp(initialPath = '/', { language = 'en' }: { language?: Language } = {}) {
  /*
   * Язык подставляется явно, а не берётся определителем: в jsdom `navigator.language`
   * — `en-US`, и страничный тест зависел бы от среды, в которой запущен, а не от того,
   * что проверяет.
   *
   * Умолчание — английский, то есть язык приложения (`DEFAULT_LANGUAGE`): тест
   * по умолчанию проверяет то, что увидит человек, открывший трекер впервые. Русский
   * подставляется явно там, где проверяется именно он.
   *
   * Смена синхронна: словари вшиты в сборку (`initAsync: false`), грузить нечего.
   */
  void i18n.changeLanguage(language);

  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false, staleTime: 0 },
      mutations: { retry: false },
    },
  });

  address.current = initialPath;

  const result = render(
    <AppProviders queryClient={queryClient}>
      <MemoryRouter initialEntries={[initialPath]}>
        <AddressProbe />
        <Routed />
      </MemoryRouter>
    </AppProviders>,
  );

  return { ...result, queryClient };
}
