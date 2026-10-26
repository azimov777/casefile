import { ownerRefHref, splitAreaAddress } from '@/shared/lib';

/** Где лежит решение: дело проекта или дело области, и его номер в этом деле. */
export interface DecisionPlace {
  /** Ключ проекта (`TRK`) или адрес области (`TRK/mcp`) — владелец дела. */
  owner: { kind: 'project' | 'area'; key: string };
  no: number;
}

/**
 * Разбор адреса решения из контракта: `TRK#15` — дело проекта, `TRK/mcp#3` — дело области.
 * Это разбор строки по её форме (как `splitAreaAddress`), а не вычисление за бэкенд: путь
 * ручки проверки собран из тех же двух частей. Строка не по форме — `null`.
 */
export function parseDecisionRef(ref: string): DecisionPlace | null {
  const hash = ref.lastIndexOf('#');
  if (hash < 0) return null;
  const no = Number(ref.slice(hash + 1));
  const key = ref.slice(0, hash);
  if (!Number.isInteger(no) || no < 1 || key === '') return null;
  return { owner: { kind: key.includes('/') ? 'area' : 'project', key }, no };
}

/** Проект, которому принадлежит решение: ключ проекта из адреса решения или области. */
export function projectOfDecision(place: DecisionPlace): string {
  return place.owner.kind === 'area'
    ? splitAreaAddress(place.owner.key).projectKey
    : place.owner.key;
}

/**
 * Куда ведёт адрес решения (`TRK#15`, `TRK/mcp#3`): экран проекта или области с раскрытой
 * записью его дела. Строка не по форме — `null`: ссылки из неё не сделать.
 */
export function decisionHref(ref: string): string | null {
  const place = parseDecisionRef(ref);
  return place === null ? null : ownerRefHref(place.owner.key, place.no);
}
