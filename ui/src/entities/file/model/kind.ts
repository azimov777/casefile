import type { FileCard } from '../api/files';

/**
 * Изображение ли файл: по типу, который хранит сервер. Показывать байты изображением
 * можно только для этих типов — остальное скачивают.
 */
export function isImage(file: Pick<FileCard, 'mime_type'>): boolean {
  return file.mime_type.toLowerCase().startsWith('image/');
}

/** Файл живой: надгробию нечего ни открыть, ни заменить, ни удалить повторно. */
export function isLive(file: Pick<FileCard, 'deleted'>): boolean {
  return !file.deleted;
}
