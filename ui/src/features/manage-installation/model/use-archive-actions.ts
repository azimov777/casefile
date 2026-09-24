import { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import {
  exportInstallationArchive,
  importInstallationArchive,
  type ArchiveImportRead,
  type InstallationArchiveUpload,
} from '../api/archive';
import { archiveFilename, saveJsonFile } from './save-file';

/** Что знает диалог приёма о своём действии: идёт ли оно и чем кончилась попытка. */
export interface Importing {
  pending: boolean;
  error: unknown;
  /** Принимает архив. Отдаёт итог вызывающему и `null`, если отказано. */
  submit: (upload: InstallationArchiveUpload) => Promise<ArchiveImportRead | null>;
  /** Забыть отказ: окно открыли заново с другим файлом. */
  reset: () => void;
}

/**
 * Выгружает архив и сохраняет его файлом — **мимо кэша запросов**: архив несёт хеши
 * паролей и токенов всей установки (`docs/moving.md`), и оставлять его в
 * `QueryClient` (виден в devtools, переживает экран) незачем — секрет выпущенного
 * токена по той же причине не мутация TanStack Query (`features/manage-access`).
 */
export function useExportArchive() {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<unknown>(null);

  return {
    pending,
    error,
    reset: () => setError(null),

    async submit() {
      setPending(true);
      setError(null);
      try {
        const upload = await exportInstallationArchive();
        saveJsonFile(upload, archiveFilename());
      } catch (cause) {
        setError(cause);
      } finally {
        setPending(false);
      }
    },
  };
}

/**
 * Принимает архив. Тоже мимо кэша мутаций: итог остаётся на экране до его собственного
 * закрытия, а не в `MutationCache`.
 *
 * Успешный приём меняет данные установки целиком — участников, проекты, задачи,
 * доступы, — и всё, что уже лежало в кэше запросов, обязано перечитаться, а не
 * достраиваться поверх замененных строк.
 */
export function useImportArchive(): Importing {
  const queryClient = useQueryClient();
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<unknown>(null);

  return {
    pending,
    error,
    reset: () => setError(null),

    async submit(upload) {
      setPending(true);
      setError(null);
      try {
        const imported = await importInstallationArchive(upload);
        await queryClient.invalidateQueries();
        return imported;
      } catch (cause) {
        setError(cause);
        return null;
      } finally {
        setPending(false);
      }
    },
  };
}
