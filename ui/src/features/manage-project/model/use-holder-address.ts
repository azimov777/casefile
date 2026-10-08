import { useCallback } from 'react';
import { useLocation, useSearchParams, type To } from 'react-router';
import { readEntryNo } from '@/shared/lib';
import {
  SEARCH_PARAM,
  holderTab,
  rememberOnTab,
  tabSearch,
  type HolderKind,
  type HolderTab,
} from './holder-tab';

/** Адрес этого же экрана с другими параметрами; пустой хвост не пишется вовсе. */
function sameScreen(pathname: string, search: URLSearchParams): To {
  const query = search.toString();
  return { pathname, search: query === '' ? '' : `?${query}` };
}

/**
 * Состояние экрана проекта или области в адресе (TRK-618): открытая вкладка
 * (`holder-tab.ts`), раскрытая запись дела (`?entry=N`) и атрибут с открытой историей
 * (`?attribute=имя`). Раньше эти правки адреса были скопированы в обеих страницах.
 *
 * Раскрытие записи и атрибута — `replace`, а не новая запись истории: раскрытие — не
 * «страница», и «назад» после трёх кликов ведёт туда, откуда человек пришёл (то же
 * правило, что у карточки задачи, `task-page.tsx`, `rememberOpen`). Смена вкладки —
 * обычный переход по ссылке (`tabHref`), то есть новая запись истории: «Назад»
 * возвращает прежнюю вкладку.
 */
export function useHolderAddress(kind: HolderKind) {
  const [searchParams, setSearchParams] = useSearchParams();
  const { pathname } = useLocation();

  const remember = useCallback(
    (name: 'entry' | 'attribute', value: string | null) => {
      setSearchParams((current) => rememberOnTab(current, kind, name, value), { replace: true });
    },
    [setSearchParams, kind],
  );

  const rememberEntry = useCallback(
    (no: number | null) => remember('entry', no === null ? null : String(no)),
    [remember],
  );
  const rememberAttribute = useCallback(
    (name: string | null) => remember('attribute', name),
    [remember],
  );

  /** Поиск по знанию области (`?q=`) — `replace`: набор слова не засоряет историю. */
  const rememberSearch = useCallback(
    (text: string) => {
      setSearchParams(
        (current) => {
          const next = new URLSearchParams(current);
          if (text === '') next.delete(SEARCH_PARAM);
          else next.set(SEARCH_PARAM, text);
          return next;
        },
        { replace: true },
      );
    },
    [setSearchParams],
  );

  /** Адрес вкладки `tab` из нынешнего адреса. */
  const tabHref = useCallback(
    (tab: HolderTab): To => sameScreen(pathname, tabSearch(searchParams, kind, tab)),
    [pathname, searchParams, kind],
  );

  /**
   * Адрес записи дела этого экрана: «Дело» с раскрытой записью `no`. Без `tab` — так же,
   * как ссылка `TRK#7` (`projectHref`): запись сама открывает «Дело».
   */
  const entryHref = useCallback(
    (no: number): To => {
      const withEntry = new URLSearchParams(searchParams);
      withEntry.set('entry', String(no));
      return sameScreen(pathname, tabSearch(withEntry, kind, 'case'));
    },
    [pathname, searchParams, kind],
  );

  return {
    tab: holderTab(searchParams, kind),
    openAt: readEntryNo(searchParams.get('entry')),
    attribute: searchParams.get('attribute'),
    search: (searchParams.get(SEARCH_PARAM) ?? '').trim(),
    rememberSearch,
    rememberEntry,
    rememberAttribute,
    tabHref,
    entryHref,
  };
}
