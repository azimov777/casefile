import { useMutation, useQueryClient } from '@tanstack/react-query';
import { fileKeys, type FileFilter } from '@/entities/file';
import { useOnceKey } from '@/shared/lib';
import { deleteFile, deleteFiles, deleteMatching, replaceFile, uploadFile } from '../api/files';

/**
 * После любого изменения файлов перечитываются все списки и карточки: файл мог попасть
 * под другой отбор, сменить имя или исчезнуть. Пересчитывать выдачу на месте клиент не
 * берётся (TRK#244) — её отдаёт сервер.
 */
function useRefreshFiles() {
  const queryClient = useQueryClient();
  return () => queryClient.invalidateQueries({ queryKey: fileKeys.all });
}

/** Загрузка файла в проект. Ключ повтора живёт, пока тот же файл уходит в тот же проект под тем же именем. */
export function useUploadFile() {
  const refresh = useRefreshFiles();
  const once = useOnceKey<{
    project: string;
    name: string;
    size: number;
    stamp: number;
    given: string;
  }>();

  return useMutation({
    mutationFn: (input: { project: string; file: File; name: string }) =>
      uploadFile(
        input,
        once.keyFor({
          project: input.project,
          name: input.name,
          given: input.file.name,
          size: input.file.size,
          stamp: input.file.lastModified,
        }),
      ),
    onSuccess: () => {
      once.forget();
      return refresh();
    },
  });
}

/** Замена содержимого файла под той же ссылкой. */
export function useReplaceFile(id: string) {
  const refresh = useRefreshFiles();
  return useMutation({
    mutationFn: (input: { file: File; name: string }) => replaceFile(id, input),
    onSuccess: refresh,
  });
}

/** Удаление одного файла. */
export function useDeleteFile() {
  const refresh = useRefreshFiles();
  return useMutation({
    mutationFn: (id: string) => deleteFile(id),
    onSuccess: refresh,
  });
}

/** Удаление нескольких: выбранных по номерам или всех под отбор с подтверждённым числом. */
export function useDeleteFiles() {
  const refresh = useRefreshFiles();
  return useMutation({
    mutationFn: (input: { ids: string[] } | { filter: FileFilter; expectedCount: number }) =>
      'ids' in input ? deleteFiles(input.ids) : deleteMatching(input.filter, input.expectedCount),
    onSuccess: refresh,
  });
}
