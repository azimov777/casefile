import { readEntryNo } from '@/shared/lib';

/*
 * Вкладки экрана проекта и страницы области (TRK-618, решение проекта TRK#46):
 * какая вкладка открыта по адресу и каким адресом открыть другую.
 *
 * Вкладка живёт в адресе (`?tab=`), а не в памяти компонента: ссылку можно переслать,
 * перезагрузка возвращает ту же вкладку, «Назад» — прежнюю. Но входящие ссылки —
 * `TRK#7`, `TRK/promotion#3`, квитанции, строка «Решения» карточки задачи — вкладку не
 * называют, они несут только `?entry=N`. Поэтому без `tab` вкладку называет то, что
 * раскрыто: запись — «Дело», атрибут — «Атрибуты». Построители ссылок
 * (`projectHref`, `areaHref`) так и остаются без вкладки.
 */

/** Чей экран: проекта или его области — у них разный набор вкладок. */
export type HolderKind = 'project' | 'area';

/** Вкладка экрана. `overview` — «Обзор» проекта, параметром адреса он не пишется. */
export type HolderTab = 'overview' | 'decisions' | 'attributes' | 'areas' | 'case';

/** Имя параметра адреса с вкладкой. */
export const TAB_PARAM = 'tab';

/** Вкладки экрана по порядку на полосе. У области нет ни «Обзора», ни решений. */
export const HOLDER_TABS: Readonly<Record<HolderKind, readonly HolderTab[]>> = {
  project: ['overview', 'decisions', 'attributes', 'areas', 'case'],
  area: ['attributes', 'case'],
};

/** Вкладка без параметра: «Обзор» у проекта, «Дело» у области (TRK-606#10, п. 7). */
const DEFAULT_TAB: Readonly<Record<HolderKind, HolderTab>> = {
  project: 'overview',
  area: 'case',
};

/** Значение `?tab=`, которое вкладка этого вида понимает. `overview` — не значение. */
function namedTab(value: string, kind: HolderKind): HolderTab | null {
  const tab = HOLDER_TABS[kind].find((candidate) => candidate === value);
  return tab === undefined || tab === DEFAULT_TAB.project ? null : tab;
}

/**
 * Какая вкладка открыта по параметрам адреса.
 *
 * Явный `tab` — он, если вид его знает; незнакомое значение (опечатка, `decisions` у
 * области) — вкладка по умолчанию, а не пустой экран. Без `tab` раскрытая запись
 * (`entry`) открывает «Дело», открытый атрибут (`attribute`) — «Атрибуты», иначе —
 * вкладка по умолчанию. Запись старше атрибута: она — то, ради чего пришли по ссылке.
 */
export function holderTab(search: URLSearchParams, kind: HolderKind): HolderTab {
  const named = search.get(TAB_PARAM);
  if (named !== null) return namedTab(named, kind) ?? DEFAULT_TAB[kind];
  if (readEntryNo(search.get('entry')) !== null) return 'case';
  if ((search.get('attribute') ?? '') !== '') return 'attributes';
  return DEFAULT_TAB[kind];
}

/**
 * Параметры адреса, открывающие вкладку `tab` из нынешних `search`.
 *
 * Раскрытое на чужой вкладке снимается: запись и отбор по типу — у всех, кроме «Дела»,
 * атрибут — у всех, кроме «Атрибутов». Иначе вернувшийся на вкладку застал бы раскрытым то, что закрыл
 * уходом, а `entry` к тому же перебивал бы вкладку по правилу выше. Остальные параметры
 * (проход по пояснениям `walk`) остаются. `tab` пишется, только когда без него правило
 * открыло бы другую вкладку: адрес «Обзора» — это адрес проекта без хвоста.
 */
export function tabSearch(
  search: URLSearchParams,
  kind: HolderKind,
  tab: HolderTab,
): URLSearchParams {
  const next = new URLSearchParams(search);
  if (tab !== 'case') {
    next.delete('entry');
    // Отбор дела по типу (`?type=`, TRK-621) — тоже состояние «Дела».
    next.delete('type');
  }
  if (tab !== 'attributes') next.delete('attribute');
  next.delete(TAB_PARAM);
  if (holderTab(next, kind) !== tab) next.set(TAB_PARAM, tab);
  return next;
}

/**
 * Параметры адреса после раскрытия или свёртывания записи (`entry`) или атрибута
 * (`attribute`) на открытой вкладке: вкладка не меняется.
 *
 * Свернув запись, пришедшую ссылкой `?entry=N`, человек остаётся в «Деле», а не
 * перескакивает на «Обзор»: если без `entry` правило дало бы другую вкладку, в адрес
 * встаёт `tab` открытой.
 */
export function rememberOnTab(
  search: URLSearchParams,
  kind: HolderKind,
  name: 'entry' | 'attribute',
  value: string | null,
): URLSearchParams {
  const tab = holderTab(search, kind);
  const next = new URLSearchParams(search);
  if (value === null) next.delete(name);
  else next.set(name, value);
  if (holderTab(next, kind) !== tab) next.set(TAB_PARAM, tab);
  return next;
}

/**
 * Параметры адреса после правки отбора по типу (`?type=`) на вкладке «Дело»: вкладка
 * остаётся «Делом». Снятый отбор у дела, открытого `?tab=case`, `tab` и так держит;
 * здесь — случай, когда «Дело» открыла запись (`?entry=N`) или адрес без `tab` вовсе.
 */
export function keepCaseTab(search: URLSearchParams, kind: HolderKind): URLSearchParams {
  if (holderTab(search, kind) !== 'case') search.set(TAB_PARAM, 'case');
  return search;
}
