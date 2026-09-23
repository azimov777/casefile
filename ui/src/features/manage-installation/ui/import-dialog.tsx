import { useTranslation } from 'react-i18next';
import { errorMessage } from '@/shared/errors';
import { Button, Callout, Dialog } from '@/shared/ui';
import type { ArchiveImportRead, InstallationArchiveUpload } from '../api/archive';
import { useImportArchive } from '../model/use-archive-actions';

/**
 * Подтверждение приёма: действие необратимо и заменяет все данные установки, поэтому
 * спрашивают о нём до, а не после (тот же образец `role="alertdialog"`, что у отзыва
 * ключа в `features/manage-access`).
 *
 * Сам файл прочитан и разобран раньше, на экране (`readArchiveFile`): здесь только
 * подтверждение и сама отправка — окно не может открыться без выбранного файла.
 */
export function ImportDialog({
  fileName,
  upload,
  onClose,
  onImported,
}: {
  /** Имя выбранного файла — человек видит, что именно сейчас отправляет. */
  fileName: string;
  upload: InstallationArchiveUpload;
  onClose: () => void;
  onImported: (result: ArchiveImportRead) => void;
}) {
  const importArchive = useImportArchive();
  const { t } = useTranslation('moving');
  const failed = importArchive.error !== null && importArchive.error !== undefined;

  async function confirm() {
    const imported = await importArchive.submit(upload);
    if (imported !== null) onImported(imported);
  }

  return (
    <Dialog
      alert
      open
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      title={t('import.confirmTitle')}
      description={t('import.confirmIntro')}
      closeLabel={t('close')}
    >
      <Callout tone="danger">{t('import.warning')}</Callout>

      <p className="max-w-(--ui-text-max) text-meta text-muted">
        {t('import.fileLabel')}: <span className="font-mono text-text">{fileName}</span>
      </p>

      <div className="flex flex-wrap gap-2">
        <Button disabled={importArchive.pending} onClick={() => void confirm()}>
          {importArchive.pending ? t('import.pending') : t('import.confirm')}
        </Button>
        <Button tone="quiet" onClick={onClose} disabled={importArchive.pending}>
          {t('cancel')}
        </Button>
      </div>

      {failed ? <Callout tone="danger">{errorMessage(importArchive.error)}</Callout> : null}
    </Dialog>
  );
}
