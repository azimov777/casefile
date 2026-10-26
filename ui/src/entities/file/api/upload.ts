import { apiClient, unwrap } from '@/shared/api';
import type { FileCard } from './files';

/**
 * Тело `multipart/form-data` собирает не генератор: схема объявляет форму, а клиент
 * шлёт её строкой. Свой сериализатор отдаёт готовый `FormData`, а заголовок типа с
 * границей ставит браузер сам. Часть `file` несёт имя и тип файла — по ним сервер
 * называет и типизирует файл; `name` идёт, только когда он задан.
 */
export function fileForm(parts: { project?: string; file: File; name: string }): FormData {
  const form = new FormData();
  if (parts.project !== undefined) form.set('project', parts.project);
  form.set('file', parts.file, parts.file.name);
  if (parts.name !== '') form.set('name', parts.name);
  return form;
}

/**
 * Кладёт файл в проект (`POST /api/v1/files`). Ключ повтора обязателен по смыслу: оборвавшуюся
 * по сети загрузку повторяют с тем же ключом, и сервер отвечает первой карточкой, а не
 * заводит второй файл. Нужна и вкладке «Файлы» (`features/manage-files`), и вложениям к
 * записям, поэтому живёт на срезе файла.
 */
export function uploadFile(
  input: { project: string; file: File; name: string },
  idempotencyKey: string,
): Promise<FileCard> {
  const form = fileForm(input);
  return unwrap(
    apiClient.POST('/api/v1/files', {
      params: { header: { 'Idempotency-Key': idempotencyKey } },
      // Тип тела в схеме — разобранная форма; здесь важна только сериализация ниже.
      body: { project: input.project, file: '' },
      bodySerializer: () => form,
    }),
  );
}
