/**
 * Тексты отказов по коду ошибки: ключ здесь — `error.code` бэкенда, а не наш
 * идентификатор (`../tracker/docs/ERRORS.md`).
 *
 * Здесь стоят коды, которыми может ответить `bootstrap`, и коды, которые придумывает
 * сам вход: экран `/login` показывает их человеку, и на английском языке они обязаны
 * быть английскими. Остальные шесть десятков кодов пока живут в
 * `shared/errors/dictionary.ts` на одном русском и переезжают сюда в UI-78; полноту
 * против справочника бэкенда оба источника проверяются вместе.
 */
export const errors = {
  actor_label_required: 'A shared agent token requires a temporary-agent label.',
  database_unavailable: 'The database is unavailable.',
  http_error: 'The request failed.',
  internal_error: 'Internal server error.',
  malformed_response: 'The server reply does not match the contract.',
  network_error: 'The server is unreachable: check that the backend is up.',
  participant_required:
    'This is a shared agent token: there is no participant behind it. A person’s token from the participant registry is required.',
  token_not_header_safe:
    'A token of this kind cannot be sent: it contains characters a token never has — most likely something extra was picked up while copying. Copy the token whole and try again.',
  too_many_requests: 'Too many requests. Try again later.',
  unauthorized: 'The token is unknown or revoked.',
} as const;
