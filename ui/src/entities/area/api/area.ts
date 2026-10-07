import { queryOptions } from '@tanstack/react-query';
import { apiClient, unwrap, unwrapPage, type Page, type components } from '@/shared/api';
import { splitAreaAddress } from '@/shared/lib';

/**
 * Область одним ответом: карточка и нынешние атрибуты (`AreaDetailRead`,
 * `../docs/CONCEPT.md`, 3.7). Атрибуты — та же схема, что у проекта (`AttributeRead`).
 */
export type AreaDetail = components['schemas']['AreaDetailRead'];

/** Карточка области без атрибутов: строка списка областей проекта. */
export type AreaCard = components['schemas']['AreaRead'];

/** Область в карточке задачи: адрес, название, описание и признак архива. */
export type TaskArea = components['schemas']['TaskAreaRead'];

/**
 * Ключи запросов области.
 *
 * Карточка и дело области — под префиксом `['area', адрес]`: он накрывает и
 * карточку, и страницы дела, и тела его записей (`entities/entry`,
 * `entryKeys.areaCase`, `entryKeys.areaBody`), как `['project', key]` у
 * проекта. Список областей — под префиксом проекта: правка карточки проекта и кадр
 * его дела перечитывают и раздел «Области», а заведение области — проект целиком.
 */
export const areaKeys = {
  detail: (address: string) => ['area', address] as const,
  list: (projectKey: string, includeArchived: boolean) =>
    ['project', projectKey, 'areas', { includeArchived }] as const,
};

/** Область по адресу `TRK/promotion`: карточка с атрибутами одним запросом. */
export function areaQueryOptions(address: string) {
  const { projectKey, areaKey } = splitAreaAddress(address);
  return queryOptions({
    queryKey: areaKeys.detail(address),
    queryFn: (): Promise<AreaDetail> =>
      unwrap(
        apiClient.GET('/api/v1/projects/{project_key}/areas/{area_key}', {
          params: { path: { project_key: projectKey, area_key: areaKey } },
        }),
      ),
  });
}

/**
 * Сколько областей читается за раз: предел контракта. Областей у проекта единицы
 * (`../docs/CONCEPT.md`, 3.7: часть работы без конца, а не задача), и страница их
 * покрывает; если однажды не покроет, раздел скажет об этом словами (`has_more`), а не
 * покажет молча первые двести.
 */
export const AREA_PAGE_SIZE = 200;

/**
 * Области проекта по ключу, порядок — по ключу области, как отдаёт бэкенд.
 * Архивные — только с `includeArchived`: без него бэкенд их прячет, как прячет архивные
 * проекты из панели.
 */
export function areasQueryOptions(projectKey: string, includeArchived = false) {
  return queryOptions({
    queryKey: areaKeys.list(projectKey, includeArchived),
    queryFn: (): Promise<Page<AreaCard>> =>
      unwrapPage(
        apiClient.GET('/api/v1/projects/{project_key}/areas', {
          params: {
            path: { project_key: projectKey },
            query: { include_archived: includeArchived, limit: AREA_PAGE_SIZE },
          },
        }),
      ),
  });
}
