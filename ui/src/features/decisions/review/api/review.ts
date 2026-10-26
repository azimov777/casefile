import type { Entry } from '@/entities/entry';
import { apiClient, unwrap } from '@/shared/api';
import { splitAreaAddress } from '@/shared/lib';
import type { DecisionPlace, ReviewOutcome } from '@/entities/decision';

/** Путь области в API: ключ проекта и ключ области двумя сегментами. */
function areaPath(address: string) {
  const { projectKey, areaKey } = splitAreaAddress(address);
  return { project_key: projectKey, area_key: areaKey };
}

export interface ReviewInput {
  place: DecisionPlace;
  outcome: ReviewOutcome;
  /** Причина: свободный текст, может быть пустой; уходит телом записи о проверке. */
  reason: string;
  idempotencyKey: string;
}

/**
 * Человек проверяет действующее решение: подтверждает, отклоняет или удаляет (TRK-756).
 * Ответ — подшитая запись `decision_review`. Отказы приходят `ApiError`: решение уже не
 * действует (`decision_not_in_force`), уже подтверждено (`decision_already_confirmed`),
 * проект в архиве (`project_archived`), записывает не человек (`403 permission_denied`).
 */
export function reviewDecision({
  place,
  outcome,
  reason,
  idempotencyKey,
}: ReviewInput): Promise<Entry> {
  const header = { 'Idempotency-Key': idempotencyKey };
  const body = { outcome, reason };
  return place.owner.kind === 'area'
    ? unwrap(
        apiClient.POST(
          '/api/v1/projects/{project_key}/areas/{area_key}/decisions/{decision_no}/review',
          {
            params: { path: { ...areaPath(place.owner.key), decision_no: place.no }, header },
            body,
          },
        ),
      )
    : unwrap(
        apiClient.POST('/api/v1/projects/{project_key}/decisions/{decision_no}/review', {
          params: { path: { project_key: place.owner.key, decision_no: place.no }, header },
          body,
        }),
      );
}

export interface ReviseInput {
  place: DecisionPlace;
  title: string;
  body: string;
  idempotencyKey: string;
}

/**
 * «Исправить»: новое решение от имени человека с `supersedes` прежнего. Бэкенд считает его
 * подтверждённым, потому что подписал человек (TRK-755, п. 7); прежнее становится заменённым.
 */
export function reviseDecision({
  place,
  title,
  body,
  idempotencyKey,
}: ReviseInput): Promise<Entry> {
  const header = { 'Idempotency-Key': idempotencyKey };
  const entry = { type: 'decision' as const, title, body, supersedes: [place.no] };
  return place.owner.kind === 'area'
    ? unwrap(
        apiClient.POST('/api/v1/projects/{project_key}/areas/{area_key}/entries', {
          params: { path: areaPath(place.owner.key), header },
          body: entry,
        }),
      )
    : unwrap(
        apiClient.POST('/api/v1/projects/{project_key}/entries', {
          params: { path: { project_key: place.owner.key }, header },
          body: entry,
        }),
      );
}
