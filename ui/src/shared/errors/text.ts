import { ApiError } from '../api';
import { i18n } from '../i18n';

/**
 * Текст ошибки для человека по коду, на языке интерфейса.
 *
 * Язык берётся из экземпляра `i18next`, а не приходит параметром: ошибку показывают
 * и компоненты, и модели отбора, и подпись у неё одна на все места. Цена названа:
 * компонент, который показывает текст отказа, обязан сам быть подписан на язык
 * (`useTranslation` где-нибудь по дороге) — иначе после смены языка он останется
 * с прежним текстом до следующей отрисовки.
 *
 * Источник текста один — пространство `errors` словарей языков. Полноту его против
 * `../docs/ERRORS.md` стережёт `text.test.ts`.
 */
export function errorText(code: string, fallback = ''): string {
  const translated = i18n.t(code, { ns: 'errors', defaultValue: '' });
  if (translated !== '') return translated;

  // Неизвестный код показывает фразу бэкенда: лучше английская правда, чем русская
  // выдумка, — и это повод дополнить словарь.
  return fallback === ''
    ? i18n.t('error.unknownCode', { code })
    : i18n.t('error.withCode', { message: fallback, code });
}

/**
 * Текст причины у поля для человека, по коду `details.fields[].reason`
 * (`shared/api/error.ts`, `ApiError.fields`).
 *
 * Источник — пространство `fieldReasons` словарей языков. В отличие от `errorText`,
 * полноту словаря никто не проверяет: бэкенд не поставляет закрытый список причин
 * (`app/domain/fields.py`), и запасной текст называет сам код вместо того, чтобы
 * ронять сборку за неизвестную причину.
 */
export function fieldReasonText(reason: string): string {
  const translated = i18n.t(reason, { ns: 'fieldReasons', defaultValue: '' });
  return translated !== '' ? translated : i18n.t('error.unknownFieldReason', { reason });
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
  return i18n.t('error.unknown');
}
