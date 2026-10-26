import { parsePath, type Path, type To } from 'react-router';
import type { DecisionRow } from '@/entities/decision';

/**
 * Отбор вкладки «Решения»: действующие, ещё не проверенные человеком, снятые. Живёт в
 * адресе (`?show=`): ссылку «Не подтверждено решений: N» можно переслать, «Назад»
 * возвращает прежний отбор.
 */
export type DecisionFilter = 'inforce' | 'unconfirmed' | 'removed';

/** Имя параметра адреса с отбором. */
export const FILTER_PARAM = 'show';

const FILTERS: readonly DecisionFilter[] = ['inforce', 'unconfirmed', 'removed'];

/** Отбор из адреса; чужое значение — отбор по умолчанию, «Действующие». */
export function readFilter(search: URLSearchParams): DecisionFilter {
  return FILTERS.find((filter) => filter === search.get(FILTER_PARAM)) ?? 'inforce';
}

/** Параметры адреса с другим отбором; «Действующие» параметром не пишется. */
export function withFilter(search: URLSearchParams, filter: DecisionFilter): URLSearchParams {
  const next = new URLSearchParams(search);
  if (filter === 'inforce') next.delete(FILTER_PARAM);
  else next.set(FILTER_PARAM, filter);
  return next;
}

/** Строки по трём отборам. Порядок — как отдал бэкенд (старые первыми). */
export interface DecisionGroups {
  inForce: DecisionRow[];
  unconfirmed: DecisionRow[];
  removed: DecisionRow[];
}

/**
 * Раскладка строк по отборам — по готовым полям строки, а не по своим правилам: действует
 * ли решение (`status`) и проверено ли (`review_state`) считает бэкенд (TRK#244). «Снятые» —
 * всё, что не действует: заменённые, отклонённые, удалённые.
 */
export function groupDecisions(rows: readonly DecisionRow[]): DecisionGroups {
  const groups: DecisionGroups = { inForce: [], unconfirmed: [], removed: [] };
  for (const row of rows) {
    if (row.status !== 'in_force') groups.removed.push(row);
    else {
      groups.inForce.push(row);
      if (row.review_state === 'unconfirmed') groups.unconfirmed.push(row);
    }
  }
  return groups;
}

/**
 * Адрес вкладки «Решения» с отбором `filter`: `tab` — адрес самой вкладки (его даёт экран
 * проекта или области), отбор дописывается к его параметрам.
 */
export function decisionsFilterHref(tab: To, filter: DecisionFilter): Partial<Path> {
  const base = typeof tab === 'string' ? parsePath(tab) : tab;
  const search = withFilter(new URLSearchParams(base.search ?? ''), filter).toString();
  return { ...base, search: search === '' ? '' : `?${search}` };
}
