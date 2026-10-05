import { projectHref } from '@/shared/lib';

/**
 * Ссылка на решение проекта — запись `decision` его дела: `TRK#15` (`../docs/CONCEPT.md`,
 * 3.2). Бэкенд отдаёт её строкой, уже канонической; разбор нужен только затем, чтобы
 * собрать адрес экрана проекта с раскрытой записью.
 */
const DECISION_REF = /^([A-Z][A-Z0-9]{1,15})#(\d+)$/;

/**
 * Адрес решения: экран его проекта с раскрытой записью дела — тот же, куда ведёт ссылка
 * `TRK#7` из текста (`shared/lib/task-refs.ts`). Строка не той формы — испорченный
 * контракт, а не рабочее состояние: ссылка ведёт на проект без раскрытия, а не никуда.
 */
export function decisionHref(ref: string): string {
  const match = DECISION_REF.exec(ref);
  if (match === null) return projectHref(ref.split('#')[0] ?? ref);
  const [, key = '', no = ''] = match;
  return projectHref(key, Number(no));
}

/**
 * Номер записи решения в деле его проекта: `TRK#15` → `15`. `null` у строки не той формы.
 */
export function decisionNo(ref: string): number | null {
  const match = DECISION_REF.exec(ref);
  return match === null ? null : Number(match[2]);
}

/**
 * Условие языка запросов «задачи, которые ссылаются на решение» (`decision: TRK#15`,
 * `../docs/CONCEPT.md`, 4.4) — обратный путь от решения к сделанному по нему. Строка
 * уходит бэкенду как есть: разбирает её он.
 */
export function decisionTasksQuery(ref: string): string {
  return `decision: ${ref}`;
}
