import { queryOptions } from '@tanstack/react-query';
import { apiClient, unwrapPage, type components } from '@/shared/api';

/**
 * Настройка установки (TRK-744): правила, что лежит в базе, что действует сейчас и кто
 * менял. Значения — текстом в каноническом виде (`168`, `true`, `PT2592000S`); разбирает
 * их `../model/amount.ts`, а не экран.
 */
export type Setting = components['schemas']['InstallationSettingRead'];

export const settingKeys = {
  all: ['settings'] as const,
  list: ['settings', 'list'] as const,
};

/**
 * Все семь настроек в порядке реестра. Читать их может любой вошедший: секретов здесь
 * нет. Без страниц — набор ограничен реестром.
 */
export function settingsQueryOptions() {
  return queryOptions({
    queryKey: settingKeys.list,
    queryFn: async (): Promise<Setting[]> =>
      (await unwrapPage(apiClient.GET('/api/v1/settings'))).items,
  });
}
