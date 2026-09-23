import { apiClient, unwrap, type components } from '@/shared/api';

export type InstallationArchive = components['schemas']['InstallationArchive'];
export type InstallationArchiveUpload = components['schemas']['InstallationArchiveUpload'];
export type ArchiveImportRead = components['schemas']['ArchiveImportRead'];

/**
 * Выгружает архив установки целиком. Требует администратора (`403 admin_required`):
 * в архиве хеши паролей всех людей и хеши всех токенов (`docs/moving.md`).
 *
 * Ответ оборачивается тем же ключом `data`, каким его вернул бы сам эндпойнт
 * (`DataResponse[InstallationArchive]`): файл, сохранённый с экрана этим объектом,
 * и есть готовое тело будущего приёма (`InstallationArchiveUpload`) — трогать его
 * не нужно ни при выгрузке, ни при приёме.
 */
export async function exportInstallationArchive(): Promise<InstallationArchiveUpload> {
  const archive = await unwrap(apiClient.GET('/api/v1/installation/archive'));
  return { data: archive };
}

/**
 * Принимает архив в эту установку. Требует администратора и установки без очередей
 * (`403 admin_required`, `409 installation_not_empty`); архив снят более новой версией
 * — `409 archive_revision_unknown`.
 *
 * Тело — файл выгрузки как есть: интерфейс не правит его и не довычисляет ничего сверх
 * того, что вернёт `ArchiveImportRead` (`docs/moving.md`, ограничения UI-135).
 * Идемпотентности у маршрута нет — повтор успевшего приёма отвечает
 * `installation_not_empty`, а не вторым приёмом (`app/api/routes/installation.py`).
 */
export function importInstallationArchive(
  upload: InstallationArchiveUpload,
): Promise<ArchiveImportRead> {
  return unwrap(apiClient.POST('/api/v1/installation/archive', { body: upload }));
}
