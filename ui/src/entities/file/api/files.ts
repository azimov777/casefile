import { infiniteQueryOptions, queryOptions } from '@tanstack/react-query';
import { ApiError, apiClient, unwrap, unwrapPage, type Page, type components } from '@/shared/api';

/**
 * Файл установки (TRK/files#3): карточка без байтов — имя, тип, размер, проект, кто и
 * когда добавил, когда открыт, сколько записей и задач на него ссылаются. Живой или
 * надгробие (`deleted`); список по умолчанию надгробий не несёт.
 */
export type FileCard = components['schemas']['FileRead'];
export type FileSort = components['schemas']['FileSort'];

/**
 * Отбор списка файлов. Всё, что здесь стоит, уходит запросом как есть: сервер ищет,
 * отбирает и сортирует (TRK#244), клиент ничего не досчитывает.
 */
export interface FileFilter {
  /** Часть имени без учёта регистра; пусто — без поиска. */
  q: string;
  /** Ключ проекта; `null` — файлы всех живых проектов. */
  project: string | null;
  /** Тип точно (`application/pdf`) или семейство (`image`); `null` — любой. */
  mimeType: string | null;
  sort: FileSort;
  /** Сначала крупные и свежие (умолчание сервера). */
  descending: boolean;
  /**
   * Только изображения, которых давно не открывали (TRK-741, TRK/files#8). Признак
   * считает сервер; интерфейс на вкладке «Файлы» его покажет в TRK-754.
   */
  unopened: boolean;
}

export const EMPTY_FILE_FILTER: FileFilter = {
  q: '',
  project: null,
  mimeType: null,
  sort: 'added',
  descending: true,
  unopened: false,
};

/** Сколько файлов на странице списка. */
export const FILE_PAGE_SIZE = 50;

export const fileKeys = {
  all: ['files'] as const,
  lists: ['files', 'list'] as const,
  list: (filter: FileFilter) => ['files', 'list', filter] as const,
  card: (id: string) => ['files', 'card', id] as const,
  bytes: (id: string) => ['files', 'bytes', id] as const,
};

/** Параметры запроса списка и удаления по отбору: то, что сервер зовёт отбором. */
export function filterQuery(filter: FileFilter) {
  return {
    q: filter.q === '' ? undefined : filter.q,
    project: filter.project ?? undefined,
    mime_type: filter.mimeType ?? undefined,
    unopened: filter.unopened ? true : undefined,
  };
}

/**
 * Файлы установки страницами по курсору. Курсор действителен при том же отборе и
 * порядке, поэтому отбор стоит в ключе запроса. `meta.total` здесь `null`: коллекция
 * не считает (TRK/ui-api#15) — число для подтверждения удаления даёт только обход всех
 * страниц (`features/manage-files`).
 */
export function filesQueryOptions(filter: FileFilter) {
  return infiniteQueryOptions({
    queryKey: fileKeys.list(filter),
    queryFn: ({ pageParam }): Promise<Page<FileCard>> =>
      unwrapPage(
        apiClient.GET('/api/v1/files', {
          params: {
            query: {
              ...filterQuery(filter),
              sort: filter.sort,
              descending: filter.descending,
              limit: FILE_PAGE_SIZE,
              cursor: pageParam === '' ? undefined : pageParam,
            },
          },
        }),
      ),
    initialPageParam: '',
    getNextPageParam: (last: Page<FileCard>) =>
      last.meta?.has_more === true ? (last.meta.next_cursor ?? undefined) : undefined,
  });
}

/** Карточка одного файла. Чтение карточки открытием файла не считается. */
export function fileQueryOptions(id: string) {
  return queryOptions({
    queryKey: fileKeys.card(id),
    queryFn: (): Promise<FileCard> =>
      unwrap(apiClient.GET('/api/v1/files/{file_id}', { params: { path: { file_id: id } } })),
  });
}

/**
 * Байты файла. `<img src>` заголовка `Authorization` не несёт, поэтому байты берутся
 * запросом `fetch` через общий клиент (токен ставит его перехватчик) и показываются через
 * `blob:`-адрес. **Каждый такой запрос — открытие файла**: сервер ставит «последний раз
 * открыт», поэтому список строк байтов не читает (миниатюры пометили бы все изображения
 * открытыми и обнулили бы признак «давно не открывали», TRK/files#8).
 */
export async function fetchFileBlob(id: string): Promise<Blob> {
  let result;
  try {
    result = await apiClient.GET('/api/v1/files/{file_id}/content', {
      params: { path: { file_id: id } },
      parseAs: 'blob',
    });
  } catch (cause) {
    if (cause instanceof ApiError) throw cause;
    throw ApiError.network(cause);
  }
  if (result.error !== undefined) {
    throw ApiError.fromBody(result.error, result.response.status);
  }
  if (result.data === undefined) throw ApiError.fromBody(null, result.response.status);
  return result.data as Blob;
}
