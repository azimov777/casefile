import { infiniteQueryOptions } from '@tanstack/react-query';
import { apiClient, unwrapPage, type Page, type components } from '@/shared/api';

/** Токен доступа без секрета: секрет живёт только в ответе на выпуск. */
export type Token = components['schemas']['TokenRead'];

/** Вид строки доступа (`kind` в контракте): чем человек узнаёт, что это за доступ. */
export type TokenKind = Token['kind'];

/** Имя ключа, которым работает интерфейс на этом компьютере: вход человека без ввода. */
export const LOCAL_SESSION_NAME = 'local-ui';

/**
 * Отозван ли доступ. Признака «отозван» в контракте нет — есть время отзыва, и
 * вопрос «жив ли ключ» это вопрос о нём (`app/api/schemas/tokens.py`).
 */
export function isRevoked(token: Token): boolean {
  return token.revoked_at !== null && token.revoked_at !== undefined;
}

/** Вход человека в интерфейс: сеанс браузера или ключ этого компьютера (`kind: session`). */
export function isSession(token: Token): boolean {
  return token.kind === 'session';
}

/** Подключение агента по OAuth (`kind: oauth`): клиент вошёл сам, секрета человек не видел. */
export function isConnection(token: Token): boolean {
  return token.kind === 'oauth';
}

/** Ключ агента (`kind: key`): статический секрет, который выпустил человек. */
export function isKey(token: Token): boolean {
  return token.kind === 'key';
}

/** Ключ интерфейса этого компьютера: сеанс без срока, его выдаёт сама установка. */
export function isThisComputer(token: Token): boolean {
  return isSession(token) && token.name === LOCAL_SESSION_NAME;
}

/**
 * Пускает ли ещё доступ. Подключение OAuth живо, пока не отозвано: срок его токена
 * клиент продлевает сам через refresh, и подключение, которым давно не ходили, всё равно
 * остаётся открытым — скрыв его, человек не смог бы его отключить. Сеанс входа живёт до
 * своего срока; ключ агента — до отзыва. Срок сравнивается с часами клиента: признака
 * «истёк» контракт не отдаёт, есть только сам срок.
 */
export function isLive(token: Token, now: number = Date.now()): boolean {
  if (isRevoked(token)) return false;
  if (!isSession(token) || token.expires_at === null || token.expires_at === undefined) {
    return true;
  }
  return Date.parse(token.expires_at) > now;
}

/**
 * Свой ли токен участнику `me`: говорит от его имени или выпущен им самим. Тот же
 * предикат, что у бэкенда (`Token.belongs_to`, TRK-114#12): свой токен человек отзывает
 * и без флага администратора. Выпущенный — только человеком: временный агент с меткой,
 * совпавшей с именем, своим его не делает.
 */
export function belongsTo(token: Token, me: string | null): boolean {
  if (me === null) return false;
  if (token.participant === me) return true;
  return token.created_by.kind === 'human' && token.created_by.signature === me;
}

export const tokenKeys = {
  all: ['tokens'] as const,
  list: (mine: boolean) => ['tokens', 'list', { mine }] as const,
};

/** Сколько доступов на странице. Столько же берёт по умолчанию и бэкенд. */
export const TOKEN_PAGE_SIZE = 50;

/**
 * Токены, включая отозванные: отзыв — часть истории, а не удаление
 * (TRK#79). Чтение открыто любому набору, в том числе `task`, —
 * поэтому список виден и тому, кому запись закрыта.
 *
 * Чьи — решает бэкенд (TRK-114): администратору все токены установки, остальным свои.
 * `mine` сужает до своих и администратора; остальным он ничего не меняет, и экран его
 * им не шлёт.
 *
 * Выдача листается курсором, как все коллекции, кроме списка задач: `meta.total`
 * здесь `null`, и «сколько всего доступов» экран не знает, пока не дочитает.
 */
export function tokensQueryOptions({ mine = false }: { mine?: boolean } = {}) {
  return infiniteQueryOptions({
    queryKey: tokenKeys.list(mine),
    queryFn: ({ pageParam }): Promise<Page<Token>> =>
      unwrapPage(
        apiClient.GET('/api/v1/tokens', {
          params: {
            query: {
              limit: TOKEN_PAGE_SIZE,
              ...(mine ? { mine: true } : {}),
              cursor: pageParam === '' ? undefined : pageParam,
            },
          },
        }),
      ),
    initialPageParam: '',
    getNextPageParam: (last: Page<Token>) =>
      last.meta?.has_more === true ? (last.meta.next_cursor ?? undefined) : undefined,
  });
}
