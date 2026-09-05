import { ApiError } from '@/shared/api';
import { errorText } from '@/shared/errors';

/**
 * Отказ бэкенда на негодный отбор, разобранный для показа у поля запроса.
 *
 * Клиент язык запросов не разбирает и не проверяет: он только показывает то, что
 * бэкенд уже сказал о строке — позицию символа и список допустимого.
 */
export interface QueryProblem {
  message: string;
  /** Позиция символа с нуля; `null` — если бэкенд её не назвал. */
  position: number | null;
  /** Строка, к которой относится позиция. */
  query: string;
  /** Допустимые поля или значения из `details.allowed`. */
  allowed: string[];
}

/** Коды, которыми бэкенд отвечает на негодный отбор (`../tracker/docs/ERRORS.md`). */
const QUERY_CODES = new Set([
  'invalid_search_query',
  'search_field_unknown',
  'search_operator_not_supported',
  'search_value_invalid',
]);

/**
 * Разбирает отказ в подсказку у поля запроса. `null` означает «это не про запрос»:
 * такой отказ показывает страница целиком, а не поле формы.
 */
export function readQueryProblem(error: unknown, query: string): QueryProblem | null {
  if (!(error instanceof ApiError) || !QUERY_CODES.has(error.code)) return null;

  const { position, allowed, query: echoed } = error.details;

  return {
    message: errorText(error.code, error.message),
    position: typeof position === 'number' ? position : null,
    // Строку возвращают не все отказы: у отбора по значению её в подробностях нет,
    // и указывать позицию приходится в той, которую отправили.
    query: typeof echoed === 'string' ? echoed : query,
    allowed: Array.isArray(allowed) ? allowed.map(String) : [],
  };
}

/** Строка-указатель под запросом: пробелы до позиции и `^` на ней. */
export function caretLine(query: string, position: number): string {
  const at = Math.max(0, Math.min(position, query.length));
  return `${' '.repeat(at)}^`;
}
