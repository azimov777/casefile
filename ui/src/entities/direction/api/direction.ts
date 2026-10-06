import { queryOptions } from '@tanstack/react-query';
import { apiClient, unwrap, unwrapPage, type Page, type components } from '@/shared/api';
import { splitDirectionAddress } from '@/shared/lib';

/**
 * Направление одним ответом: карточка и нынешние атрибуты (`DirectionDetailRead`,
 * `../docs/CONCEPT.md`, 3.7). Атрибуты — та же схема, что у проекта (`AttributeRead`).
 */
export type DirectionDetail = components['schemas']['DirectionDetailRead'];

/** Карточка направления без атрибутов: строка списка направлений проекта. */
export type DirectionCard = components['schemas']['DirectionRead'];

/** Направление в карточке задачи: адрес, название, описание и признак архива. */
export type TaskDirection = components['schemas']['TaskDirectionRead'];

/**
 * Ключи запросов направления.
 *
 * Карточка и дело направления — под префиксом `['direction', адрес]`: он накрывает и
 * карточку, и страницы дела, и тела его записей (`entities/entry`,
 * `entryKeys.directionCase`, `entryKeys.directionBody`), как `['project', key]` у
 * проекта. Список направлений — под префиксом проекта: правка карточки проекта и кадр
 * его дела перечитывают и раздел «Направления», а заведение направления — проект целиком.
 */
export const directionKeys = {
  detail: (address: string) => ['direction', address] as const,
  list: (projectKey: string, includeArchived: boolean) =>
    ['project', projectKey, 'directions', { includeArchived }] as const,
};

/** Направление по адресу `TRK/promotion`: карточка с атрибутами одним запросом. */
export function directionQueryOptions(address: string) {
  const { projectKey, directionKey } = splitDirectionAddress(address);
  return queryOptions({
    queryKey: directionKeys.detail(address),
    queryFn: (): Promise<DirectionDetail> =>
      unwrap(
        apiClient.GET('/api/v1/projects/{project_key}/directions/{direction_key}', {
          params: { path: { project_key: projectKey, direction_key: directionKey } },
        }),
      ),
  });
}

/**
 * Сколько направлений читается за раз: предел контракта. Направлений у проекта единицы
 * (`../docs/CONCEPT.md`, 3.7: часть работы без конца, а не задача), и страница их
 * покрывает; если однажды не покроет, раздел скажет об этом словами (`has_more`), а не
 * покажет молча первые двести.
 */
export const DIRECTION_PAGE_SIZE = 200;

/**
 * Направления проекта по ключу, порядок — по ключу направления, как отдаёт бэкенд.
 * Архивные — только с `includeArchived`: без него бэкенд их прячет, как прячет архивные
 * проекты из панели.
 */
export function directionsQueryOptions(projectKey: string, includeArchived = false) {
  return queryOptions({
    queryKey: directionKeys.list(projectKey, includeArchived),
    queryFn: (): Promise<Page<DirectionCard>> =>
      unwrapPage(
        apiClient.GET('/api/v1/projects/{project_key}/directions', {
          params: {
            path: { project_key: projectKey },
            query: { include_archived: includeArchived, limit: DIRECTION_PAGE_SIZE },
          },
        }),
      ),
  });
}
