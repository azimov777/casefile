import { ApiError } from '@/shared/api';

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
