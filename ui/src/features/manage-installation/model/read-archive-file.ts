import { ApiError } from '@/shared/api';
import type { InstallationArchiveUpload } from '../api/archive';

/**
 * Читает выбранный файл как тело приёма — как есть, без правки и без проверки схемы:
 * схему проверяет бэкенд (`422 archive_invalid`, `422 archive_format_unsupported`).
 * Здесь только то, без чего запрос не собрать: файл обязан читаться как текст и
 * разбираться как JSON.
 *
 * Отказ на этом шаге переиспользует код `archive_format_unsupported` — тот же, каким
 * бэкенд отвечает на файл, который не архив вовсе: для человека это один и тот же
 * случай, «выбран не тот файл», и второй текст под него заводить незачем.
 */
export async function readArchiveFile(file: File): Promise<InstallationArchiveUpload> {
  const text = await file.text();
  try {
    return JSON.parse(text) as InstallationArchiveUpload;
  } catch {
    throw new ApiError('archive_format_unsupported', 'The file is not valid JSON', 0, {});
  }
}
