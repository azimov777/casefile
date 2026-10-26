import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import type { FileCard } from '@/entities/file';
import { errorMessage } from '@/shared/errors';
import { Button, Callout, Dialog } from '@/shared/ui';
import { useDeleteFile } from '../model/use-file-actions';

/**
 * Кнопка «Удалить» у файла и окно подтверждения. Удаление стирает байты насовсем и
 * оставляет надгробие (TRK/files#3), поэтому спрашивается окном `alertdialog`, где сказано,
 * сколько записей и задач на файл ссылаются.
 */
export function DeleteDialog({ file }: { file: FileCard }) {
  const [open, setOpen] = useState(false);
  const { t } = useTranslation('files');

  return (
    <Dialog
      alert
      open={open}
      onOpenChange={setOpen}
      title={t('remove.singleTitle', { name: file.name })}
      description={t('remove.singleIntro')}
      closeLabel={t('close')}
      trigger={
        <Button tone="quiet" size="sm">
          {t('actions.delete')}
        </Button>
      }
    >
      <DeleteForm file={file} onClose={() => setOpen(false)} />
    </Dialog>
  );
}

function DeleteForm({ file, onClose }: { file: FileCard; onClose: () => void }) {
  const remove = useDeleteFile();
  const { t } = useTranslation('files');
  const failed = remove.error !== null && remove.error !== undefined;

  return (
    <>
      <p className="text-body" data-role="refs">
        {file.entries === 0
          ? t('item.noRefs')
          : t('item.refs', { count: file.entries, tasks: file.tasks })}
      </p>

      <div className="flex flex-wrap gap-2">
        <Button
          disabled={remove.isPending}
          onClick={() => remove.mutate(file.id, { onSuccess: onClose })}
        >
          {remove.isPending ? t('remove.pending') : t('remove.confirm')}
        </Button>
        <Button tone="quiet" onClick={onClose}>
          {t('cancel')}
        </Button>
      </div>

      {failed ? <Callout tone="danger">{errorMessage(remove.error)}</Callout> : null}
    </>
  );
}
