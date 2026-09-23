import { ApiError } from '@/shared/api';

/**
 * Поля, на которые жалуется отказ.
 *
 * Источников два, и оба приходят от бэкенда: `details.fields` — замечания предметной
 * области (`../docs/ERRORS.md`), `details.errors` — разбор схемы запроса
 * (`validation_error`, форма Pydantic, где имя поля стоит последним куском `loc`).
 * Имя поля, найденное здесь, только **находит** объяснение в словаре — сам текст
 * объяснения пишет экран: что значит «имя не подошло», знает он, а не отказ.
 */
export function invalidFields(error: unknown): string[] {
  if (!(error instanceof ApiError)) return [];

  const fromDomain = Object.keys(error.fields ?? {});
  const fromSchema = schemaErrors(error).flatMap((entry) => {
    const location = Array.isArray(entry.loc) ? entry.loc : [];
    const field = location.at(-1);
    return typeof field === 'string' ? [field] : [];
  });

  return [...new Set([...fromDomain, ...fromSchema])];
}

/** Жалуется ли отказ на это поле. */
export function complainsAbout(error: unknown, field: string): boolean {
  return invalidFields(error).includes(field);
}

function schemaErrors(error: ApiError): { loc?: unknown }[] {
  const errors = error.details.errors;
  return Array.isArray(errors) ? (errors as { loc?: unknown }[]) : [];
}

/**
 * Причины отказа `403 permission_denied` у доступов, которые экран объясняет своими
 * словами (TRK-114#12). Текст кода ошибки говорит «запрещено этим токеном», а почему —
 * знает только `details.reason`: без него человек решил бы, что дело в наборе.
 */
export const DENIAL_REASONS = ['account_required', 'foreign_human', 'not_own_token'] as const;

export type DenialReason = (typeof DENIAL_REASONS)[number];

/** Знакомая экрану причина отказа в праве или `null`, если отказ другой. */
export function denialReason(error: unknown): DenialReason | null {
  if (!(error instanceof ApiError) || error.code !== 'permission_denied') return null;
  const reason = error.details.reason;
  return DENIAL_REASONS.find((known) => known === reason) ?? null;
}
