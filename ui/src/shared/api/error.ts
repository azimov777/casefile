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

  /** Замечания по полям из `details.fields`: их показывают у самих полей. */
  get fields(): Record<string, string> | null {
    const fields = this.details.fields;
    if (fields === null || typeof fields !== 'object') return null;
    const entries = Object.entries(fields as Record<string, unknown>).map(
      ([name, reason]) => [name, String(reason)] as const,
    );
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
