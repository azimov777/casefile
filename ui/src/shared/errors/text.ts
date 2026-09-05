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
