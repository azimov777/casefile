import { useQuery } from '@tanstack/react-query';
import { bootstrapQueryOptions } from '@/entities/session';
import type { components } from '@/shared/api';

type Account = components['schemas']['AccountRead'];

/**
 * Учётная запись вошедшего вместе с её состоянием знакомства, для панели пояснения
 * и действия «Показать пояснения снова» (TRK-362). `null` до ответа `bootstrap`
 * (пояснение не рисуется до этого момента — constraints задачи, оно не должно мигнуть
 * человеку, который уже его скрыл) и для участника без учётной записи (`TRK-360#17`):
 * агент, вошедший общим токеном, пояснений не видит.
 */
export function useOnboardingHints(): Account | null {
  const bootstrap = useQuery(bootstrapQueryOptions());
  if (!bootstrap.isSuccess) return null;
  return bootstrap.data.account ?? null;
}
