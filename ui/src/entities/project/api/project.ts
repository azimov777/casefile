import { queryOptions } from '@tanstack/react-query';
import { apiClient, unwrap, type components } from '@/shared/api';

/** Проект одним ответом: карточка и нынешние атрибуты (`ProjectDetailRead`, TRK-157). */
export type ProjectDetail = components['schemas']['ProjectDetailRead'];

/** Атрибут проекта: имя, нынешнее значение и время. История — записями дела проекта. */
export type ProjectAttribute = components['schemas']['AttributeRead'];

/**
 * Ключи запросов проекта.
 *
 * Префикс `['project', key]` накрывает и карточку, и дело проекта с телами его записей
 * (`entities/entry`, `entryKeys.projectCase`, `entryKeys.projectBody`) — как
 * `['task', key]` накрывает пакет задачи и её дело.
 */
export const projectKeys = {
  detail: (key: string) => ['project', key] as const,
};

/**
 * Карточка проекта с атрибутами одним запросом: ключ, название, описание и нынешние
 * значения атрибутов в порядке имени без учёта регистра — порядок задаёт бэкенд.
 */
export function projectQueryOptions(key: string) {
  return queryOptions({
    queryKey: projectKeys.detail(key),
    queryFn: (): Promise<ProjectDetail> =>
      unwrap(
        apiClient.GET('/api/v1/projects/{project_key}', { params: { path: { project_key: key } } }),
      ),
  });
}
