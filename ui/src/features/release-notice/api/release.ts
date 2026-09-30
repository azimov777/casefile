import { queryOptions } from '@tanstack/react-query';
import { apiClient, unwrap, type components } from '@/shared/api';

export type ReleaseState = components['schemas']['ReleaseRead'];

/** Раз в час: так часто выпуск читает и сам бэкенд (`TRK-416`). */
export const RELEASE_REFRESH_MS = 60 * 60 * 1000;

export const releaseKeys = {
  release: ['installation', 'release'] as const,
};

/**
 * Версия установки и последний выпуск Casefile.
 *
 * В GitHub ходит бэкенд, а не вкладка: интерфейс ходит только в свой API, и тот отвечает
 * запомненным не чаще раза в час. Вкладка читает ответ при открытии и дальше раз в час —
 * фоновой тоже: плашка обязана появиться у открытой с утра вкладки, а запрос дешёвый.
 * Повтора на отказ нет: плашка — подсказка, и без ответа её просто нет.
 */
export function releaseQueryOptions() {
  return queryOptions({
    queryKey: releaseKeys.release,
    queryFn: () => unwrap(apiClient.GET('/api/v1/installation/release')),
    staleTime: RELEASE_REFRESH_MS,
    refetchInterval: RELEASE_REFRESH_MS,
    refetchIntervalInBackground: true,
    retry: false,
  });
}
