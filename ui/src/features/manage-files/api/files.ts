import { apiClient, unwrap, type components } from '@/shared/api';
import { fileForm, filterQuery, uploadFile, type FileCard, type FileFilter } from '@/entities/file';

export { uploadFile };

export type FilesDeleted = components['schemas']['FilesDeleted'];

/** Кладёт новые байты под ту же ссылку (`PUT /api/v1/files/{id}/content`). */
export function replaceFile(id: string, input: { file: File; name: string }): Promise<FileCard> {
  const form = fileForm(input);
  return unwrap(
    apiClient.PUT('/api/v1/files/{file_id}/content', {
      params: { path: { file_id: id } },
      body: { file: '' },
      bodySerializer: () => form,
    }),
  );
}

/** Удаляет один файл: байты стираются, отдаётся надгробие. */
export function deleteFile(id: string): Promise<FileCard> {
  return unwrap(apiClient.DELETE('/api/v1/files/{file_id}', { params: { path: { file_id: id } } }));
}

/** Удаляет выбранные: все или ни одного (`ids`). */
export function deleteFiles(ids: string[]): Promise<FilesDeleted> {
  return unwrap(apiClient.POST('/api/v1/files/delete', { body: { ids } }));
}

/**
 * Удаляет все файлы под отбор. `expectedCount` — число, которое человек увидел и
 * подтвердил: не совпало с числом подходящих на сервере — `409 file_count_mismatch`, и
 * ничего не удалено.
 */
export function deleteMatching(filter: FileFilter, expectedCount: number): Promise<FilesDeleted> {
  return unwrap(
    apiClient.POST('/api/v1/files/delete', {
      body: { expected_count: expectedCount, ...filterQuery(filter) },
    }),
  );
}
