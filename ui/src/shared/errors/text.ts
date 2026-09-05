import { ApiError } from '../api';
import { errorDictionary } from './dictionary';

/**
 * Текст ошибки для человека по коду. Неизвестный код показывает фразу бэкенда:
 * лучше английская правда, чем русская выдумка, — и это повод дополнить словарь.
 */
export function errorText(code: string, fallback = ''): string {
  const known = errorDictionary[code];
  if (known !== undefined) return known;
  return fallback === '' ? `Неизвестная ошибка (${code}).` : `${fallback} (${code})`;
}

/**
 * Текст для человека по любому брошенному значению: отказ бэкенда, обрыв сети,
 * исключение в коде.
 *
 * Живёт здесь, а не на страницах: до этой функции каждый экран разбирал ошибку
 * своей копией `describe`, и стоило добавить экран — появлялась четвёртая.
 */
export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return errorText(error.code, error.message);
  if (error instanceof Error) return error.message;
  return 'Неизвестная ошибка.';
}
