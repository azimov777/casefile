import type { components } from './openapi';

export type ErrorDetail = components['schemas']['ErrorDetail'];

/** Код, который приложение придумывает само: у бэкенда таких ответов нет. */
export const CLIENT_ERROR_CODES = {
  /** Запрос не дошёл: сеть, отменённый запрос, недоступный сервер. */
  network: 'network_error',
  /** Ответ пришёл, но не в оболочке контракта. */
  malformed: 'malformed_response',
  /** Токен рабочий, но участника за ним нет: общий агентский токен. */
  participantRequired: 'participant_required',
  /**
   * Из значения нельзя собрать заголовок `Authorization`: в нём символы, которые
   * браузер туда не пустит. Запроса при этом не было — и выдавать это за отказ
   * сети значит послать человека чинить бэкенд вместо буфера обмена.
   */
  tokenNotHeaderSafe: 'token_not_header_safe',
} as const;

/**
 * Ошибка API в том виде, в каком её принимают решения: код стабилен, по нему
 * выбирается текст (`shared/errors`), `details` показываются у полей формы.
 * `message` — техническая фраза бэкенда, годится только в запасной вариант и в журнал.
 */
export class ApiError extends Error {
  readonly code: string;
  readonly status: number;
  readonly details: Record<string, unknown>;

  constructor(code: string, message: string, status: number, details: Record<string, unknown>) {
    super(message);
    this.name = 'ApiError';
    this.code = code;
    this.status = status;
    this.details = details;
  }

  /**
   * Замечания по полям из `details.fields`: причина по имени поля. Бэкенд шлёт их
   * **списком** — `[{field, reason, ...}]` (`app/domain/fields.py`), не объектом
   * `{поле: причина}`: старый разбор объектом читал `Object.entries` списка по
   * индексам (`"0"`, `"1"`, ...) и ни разу не совпадал с именем настоящего поля
   * (UI-165). Текст причины ищет `shared/errors` (`fieldReasonText`) — здесь только
   * код `snake_case`, часть контракта.
   */
  get fields(): Record<string, string> | null {
    const raw = this.details.fields;
    if (!Array.isArray(raw)) return null;
    const entries = raw.filter(isFieldProblem).map(({ field, reason }) => [field, reason] as const);
    return entries.length > 0 ? Object.fromEntries(entries) : null;
  }

  /** Разбирает тело ошибки бэкенда; тело неизвестной формы не выдаётся за контракт. */
  static fromBody(body: unknown, status: number): ApiError {
    const detail = readErrorDetail(body);
    if (detail === null) {
      return new ApiError(
        CLIENT_ERROR_CODES.malformed,
        `Ответ со статусом ${status} не разбирается как ошибка контракта`,
        status,
        {},
      );
    }
    return new ApiError(detail.code, detail.message, status, detail.details ?? {});
  }

  static network(cause: unknown): ApiError {
    return new ApiError(
      CLIENT_ERROR_CODES.network,
      cause instanceof Error ? cause.message : 'Request failed',
      0,
      {},
    );
  }
}

/**
 * Одна запись `details.fields`: `{field, reason, ...}` (`app/domain/fields.py`).
 * Подробности сверх этих двух ключей (`allowed`, `max`, `got`, ...) существуют, но
 * эта форма их не разбирает — им нет читателя на клиенте.
 */
function isFieldProblem(value: unknown): value is { field: string; reason: string } {
  if (value === null || typeof value !== 'object') return false;
  const { field, reason } = value as Record<string, unknown>;
  return typeof field === 'string' && typeof reason === 'string';
}

function readErrorDetail(body: unknown): ErrorDetail | null {
  if (body === null || typeof body !== 'object' || !('error' in body)) return null;
  const error = (body as { error: unknown }).error;
  if (error === null || typeof error !== 'object') return null;
  const { code, message, details } = error as Record<string, unknown>;
  if (typeof code !== 'string' || typeof message !== 'string') return null;
  return {
    code,
    message,
    details: (details ?? {}) as Record<string, unknown>,
  };
}
