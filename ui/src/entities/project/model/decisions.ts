import { areaHref, projectHref } from '@/shared/lib';

/**
 * Ссылка на решение проекта — запись `decision` его дела: `TRK#15` (TRK#88).
 * Бэкенд отдаёт её строкой, уже канонической; разбор нужен только затем, чтобы
 * собрать адрес экрана проекта с раскрытой записью.
 */
const DECISION_REF = /^([A-Z][A-Z0-9]{1,15})#(\d+)$/;

/**
 * Ссылка на решение области — запись `decision` дела области: `TRK/mcp#3` (TRK#57, §5).
 * Пакет задачи несёт такие ссылки рядом с решениями проекта (поле `decisions`).
 */
const AREA_DECISION_REF = /^([A-Z][A-Z0-9]{1,15}\/[a-z0-9](?:[a-z0-9-]{0,30}[a-z0-9])?)#(\d+)$/;

/**
 * Адрес решения: экран его проекта с раскрытой записью дела — тот же, куда ведёт ссылка
 * `TRK#7` из текста (`shared/lib/task-refs.ts`). Строка не той формы — испорченный
 * контракт, а не рабочее состояние: ссылка ведёт на проект без раскрытия, а не никуда.
 */
export function decisionHref(ref: string): string {
  const inArea = AREA_DECISION_REF.exec(ref);
  if (inArea !== null) return areaHref(inArea[1] ?? '', Number(inArea[2]));
  const match = DECISION_REF.exec(ref);
  if (match === null) return projectHref(ref.split('#')[0] ?? ref);
  const [, key = '', no = ''] = match;
  return projectHref(key, Number(no));
}

/**
 * Номер записи решения в деле его проекта или области: `TRK#15` → `15`, `TRK/mcp#3` → `3`. `null` у строки не той формы.
 */
export function decisionNo(ref: string): number | null {
  const match = DECISION_REF.exec(ref) ?? AREA_DECISION_REF.exec(ref);
  return match === null ? null : Number(match[2]);
}

/**
 * Условие языка запросов «задачи, которые ссылаются на решение» (`decision: TRK#15`,
 * TRK#166) — обратный путь от решения к сделанному по нему. Строка
 * уходит бэкенду как есть: разбирает её он.
 */
export function decisionTasksQuery(ref: string): string {
  return `decision: ${ref}`;
}
