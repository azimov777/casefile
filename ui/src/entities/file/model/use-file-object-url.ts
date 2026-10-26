import { useEffect, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { fetchFileBlob, fileKeys } from '../api/files';

/**
 * `blob:`-адрес байтов файла и состояние чтения. Читает файл запросом `fetch` с токеном
 * (`fetchFileBlob`), только пока `enabled`: каждое чтение — открытие файла для сервера.
 *
 * Адрес создаётся на блок и отзывается, когда блок исчез или файл другой: иначе память
 * вкладки росла бы с каждым просмотром. В кэше запросов байты не остаются (`gcTime: 0`),
 * а повторный просмотр читает файл заново и честно считается новым открытием.
 */
export function useFileObjectUrl(id: string, enabled: boolean) {
  const query = useQuery({
    queryKey: fileKeys.bytes(id),
    queryFn: () => fetchFileBlob(id),
    enabled,
    gcTime: 0,
    staleTime: Infinity,
    retry: false,
  });
  const blob = query.data;
  const [url, setUrl] = useState<string | null>(null);
  const queryClient = useQueryClient();

  // Прочитанные байты — открытие файла: «последний раз открыт» в списках устарело.
  useEffect(() => {
    if (blob !== undefined) void queryClient.invalidateQueries({ queryKey: fileKeys.lists });
  }, [blob, queryClient]);

  useEffect(() => {
    if (blob === undefined) {
      setUrl(null);
      return;
    }
    const made = URL.createObjectURL(blob);
    setUrl(made);
    return () => URL.revokeObjectURL(made);
  }, [blob]);

  return { url, blob, query };
}
