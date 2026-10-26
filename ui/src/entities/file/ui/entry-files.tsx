import { useState } from 'react';
import { FileText } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { Button, RelativeTime } from '@/shared/ui';
import type { FileCard } from '../api/files';
import { isImage, isLive } from '../model/kind';
import { useFormatBytes } from '../model/format-bytes';
import { FileDownloadButton } from './file-download-button';
import { FileImage } from './file-image';

/**
 * Файлы записи дела в порядке вложения. Живой файл — карточка: имя, тип, размер и
 * «Скачать»; у изображения ещё «Открыть». Картинка разворачивается только по клику:
 * чтение байтов — открытие файла для сервера, и миниатюра при отрисовке ленты сняла бы
 * признак «давно не открывали» у каждого изображения (TRK-741). Удалённый — надгробие:
 * «файл удалён», кто и когда.
 */
export function EntryFiles({ files }: { files?: FileCard[] | null }) {
  const { t } = useTranslation('files');
  if (files == null || files.length === 0) return null;

  return (
    <ul aria-label={t('entryFiles.label')} className="flex list-none flex-col gap-2 p-0">
      {files.map((file) => (
        <li key={file.id} data-entry-file={file.id}>
          {isLive(file) ? <LiveFile file={file} /> : <Tombstone file={file} />}
        </li>
      ))}
    </ul>
  );
}

function LiveFile({ file }: { file: FileCard }) {
  const { t } = useTranslation('files');
  const formatBytes = useFormatBytes();
  const [shown, setShown] = useState(false);

  return (
    <div className="flex min-w-0 flex-col gap-2 rounded-control border border-line bg-sunken p-3">
      <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-2">
        <FileText className="size-(--ui-mark) shrink-0 text-faint" aria-hidden="true" />
        <span data-role="name" className="min-w-0 font-medium wrap-anywhere text-text">
          {file.name}
        </span>
        <span data-role="type" className="font-mono text-meta wrap-anywhere text-muted">
          {file.mime_type}
        </span>
        <span data-role="size" className="text-meta text-muted">
          {formatBytes(file.size_bytes)}
        </span>
        <span className="flex flex-wrap items-center gap-2">
          {isImage(file) ? (
            <Button
              type="button"
              tone="quiet"
              size="sm"
              aria-expanded={shown}
              onClick={() => setShown(!shown)}
            >
              {shown ? t('entryFiles.hide') : t('actions.open')}
            </Button>
          ) : null}
          <FileDownloadButton file={file} />
        </span>
      </div>
      {shown ? (
        <FileImage file={file} className="max-h-[70vh] max-w-full self-start object-contain" />
      ) : null}
    </div>
  );
}

function Tombstone({ file }: { file: FileCard }) {
  const { t } = useTranslation('files');
  const by = file.deleted_by?.signature ?? null;
  return (
    <p
      data-role="deleted"
      className="flex flex-wrap items-center gap-x-2 gap-y-1 rounded-control border border-dashed border-line-strong p-3 text-meta text-muted"
    >
      <span className="font-medium text-text">{t('entryFiles.deleted')}</span>
      <span className="wrap-anywhere">{file.name}</span>
      <span>
        {by === null ? t('entryFiles.deletedByTracker') : t('entryFiles.deletedBy', { author: by })}{' '}
        {file.deleted_at == null ? null : <RelativeTime value={file.deleted_at} />}
      </span>
    </p>
  );
}
