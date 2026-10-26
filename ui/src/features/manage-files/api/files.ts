import { apiClient, unwrap, type components } from '@/shared/api';
import { filterQuery, type FileCard, type FileFilter } from '@/entities/file';

export type FilesDeleted = components['schemas']['FilesDeleted'];

/**
 * Тело `multipart/form-data` собирает не генератор: схема объявляет форму, а клиент
 * шлёт её строкой. Свой сериализатор отдаёт готовый `FormData`, а заголовок типа с
 * границей ставит браузер сам. Часть `file` несёт имя и тип файла — по ним сервер
 * называет и типизирует файл; `name` идёт, только когда он задан.
 */
function formOf(parts: { project?: string; file: File; name: string }): FormData {
  const form = new FormData();
  if (parts.project !== undefined) form.set('project', parts.project);
  form.set('file', parts.file, parts.file.name);
  if (parts.name !== '') form.set('name', parts.name);
  return form;
}

/**
 * Кладёт файл в проект (`POST /api/v1/files`). Ключ повтора обязателен по смыслу: оборвавшуюся
 * по сети загрузку повторяют с тем же ключом, и сервер отвечает первой карточкой, а не
 * заводит второй файл.
 */
export function uploadFile(
  input: { project: string; file: File; name: string },
  idempotencyKey: string,
): Promise<FileCard> {
  const form = formOf(input);
  return unwrap(
    apiClient.POST('/api/v1/files', {
      params: { header: { 'Idempotency-Key': idempotencyKey } },
      // Тип тела в схеме — разобранная форма; здесь важна только сериализация ниже.
      body: { project: input.project, file: '' },
      bodySerializer: () => form,
    }),
  );
}

/** Кладёт новые байты под ту же ссылку (`PUT /api/v1/files/{id}/content`). */
export function replaceFile(id: string, input: { file: File; name: string }): Promise<FileCard> {
  const form = formOf(input);
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
