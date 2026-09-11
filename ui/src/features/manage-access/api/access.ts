import { queryOptions } from '@tanstack/react-query';
import {
  apiClient,
  unwrap,
  unwrapEmpty,
  unwrapPage,
  type components,
  type operations,
} from '@/shared/api';

export type Participant = components['schemas']['ParticipantRead'];
export type TokenScope = components['schemas']['TokenScope'];

/**
 * Выпущенный токен: единственный ответ контракта, в котором есть секрет
 * (`app/api/routes/tokens.py`). Дальше секрета нет нигде — ни в списке, ни в базе.
 */
export type IssuedToken = components['schemas']['TokenIssued'];

type IssueBody = NonNullable<
  operations['issue_token']['requestBody']
>['content']['application/json'];

export const participantKeys = {
  all: ['participants'] as const,
};

/** Сколько участников просить за раз. Потолок страницы у бэкенда — столько же. */
const PARTICIPANT_PAGE_SIZE = 200;

/**
 * Реестр участников целиком: из него человек выбирает, кому выпускать токен.
 *
 * Выдача обходится курсором до конца, а не читается одной страницей: список выбора
 * обязан называть **всех**, иначе участник, не поместившийся на первую страницу,
 * молча исчез бы из формы вместе с возможностью выпустить ему доступ.
 */
export function participantsQueryOptions() {
  return queryOptions({
    queryKey: participantKeys.all,
    queryFn: () => readParticipants(),
    staleTime: 60_000,
  });
}

async function readParticipants(): Promise<Participant[]> {
  const all: Participant[] = [];
  let cursor: string | undefined;

  do {
    const page = await unwrapPage(
      apiClient.GET('/api/v1/participants', {
        params: { query: { limit: PARTICIPANT_PAGE_SIZE, cursor } },
      }),
    );
    all.push(...page.items);
    cursor = page.meta?.has_more === true ? (page.meta.next_cursor ?? undefined) : undefined;
  } while (cursor !== undefined);

  return all;
}

export interface AgentInput {
  name: string;
  description: string;
  /** Ключ повтора: тот же на каждой попытке завести этого участника. */
  idempotencyKey: string;
}

/**
 * Заводит агента-участника. Требует набора `main`.
 *
 * Род зашит: людей на этом экране не заводят — человек уже есть, иначе он не открыл бы
 * интерфейс. Имя дальше неизменяемо: оно стоит подписью в записях дела.
 */
export function registerAgent({
  name,
  description,
  idempotencyKey,
}: AgentInput): Promise<Participant> {
  return unwrap(
    apiClient.POST('/api/v1/participants', {
      params: { header: { 'Idempotency-Key': idempotencyKey } },
      body: { kind: 'agent', name, description },
    }),
  );
}

export interface IssueInput {
  /** Имя участника или `null` — тогда выпускается общий агентский токен. */
  participant: string | null;
  scope: TokenScope;
  /** Чем токен отличают в списке при отзыве. */
  name: string;
  idempotencyKey: string;
}

/**
 * Выпускает токен и возвращает его секрет. Требует набора `main`.
 *
 * Ответ **не** кладётся в кэш запросов: секрет живёт только в состоянии экрана и
 * исчезает с закрытием окна (`UI-106#18`). Повтор с тем же `Idempotency-Key` сутки
 * отдаёт тот же секрет — иначе оборвавшийся по сети запрос оставлял бы на установке
 * действующий токен, которого никто не видел.
 */
export function issueToken({
  participant,
  scope,
  name,
  idempotencyKey,
}: IssueInput): Promise<IssuedToken> {
  const body: IssueBody = { name, scope, ...(participant === null ? {} : { participant }) };

  return unwrap(
    apiClient.POST('/api/v1/tokens', {
      params: { header: { 'Idempotency-Key': idempotencyKey } },
      body,
    }),
  );
}

/**
 * Отзывает токен. Требует набора `main`, идемпотентен и необратим: запись остаётся
 * в базе с проставленным `revoked_at`, но пускать этот секрет больше не будет.
 *
 * Ответ без тела (`204`), поэтому разворачивать нечего — проверяется только отказ.
 */
export function revokeToken(tokenId: string): Promise<void> {
  return unwrapEmpty(
    apiClient.DELETE('/api/v1/tokens/{token_id}', { params: { path: { token_id: tokenId } } }),
  );
}
