import { useEffect } from 'react';
import { useInfiniteQuery } from '@tanstack/react-query';
import { filesQueryOptions, type FileCard, type FileFilter } from '@/entities/file';

/**
 * Все файлы под отбор: страницы дочитываются до конца. Нужны окну удаления «всех
 * отобранных»: список файлов не считает (`meta.total` — `null`, TRK/ui-api#15), и число
 * для подтверждения — это число строк, которые сервер отдал. Запрос тот же, что у самого
 * списка, и страницы из его кэша берутся готовыми.
 *
 * Читает только пока `enabled`, то есть пока окно открыто.
 */
export function useAllMatching(filter: FileFilter, enabled: boolean) {
  const query = useInfiniteQuery({ ...filesQueryOptions(filter), enabled });
  const { hasNextPage, isFetchingNextPage, error, fetchNextPage } = query;

  useEffect(() => {
    if (enabled && hasNextPage && !isFetchingNextPage && (error === null || error === undefined)) {
      void fetchNextPage();
    }
  }, [enabled, hasNextPage, isFetchingNextPage, error, fetchNextPage]);

  const files: FileCard[] = query.data?.pages.flatMap((page) => page.items) ?? [];
  const failed = error !== null && error !== undefined;
  // Число известно, когда страниц больше нет и ни одна не читается: раньше его назвать нельзя.
  const ready = enabled && !query.isPending && !hasNextPage && !isFetchingNextPage && !failed;

  return { files, ready, failed, error, retry: () => void query.refetch() };
}
