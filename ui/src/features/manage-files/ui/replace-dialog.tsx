import { useState, type FormEvent } from 'react';
import { useTranslation } from 'react-i18next';
import type { FileCard } from '@/entities/file';
import { errorMessage } from '@/shared/errors';
import { Button, Callout, Dialog } from '@/shared/ui';
import { useReplaceFile } from '../model/use-file-actions';
import { FileField } from './file-field';

/**
 * Кнопка «Заменить» у файла и окно замены: новые байты ложатся под ту же ссылку, прежние
 * стираются, истории версий нет (TRK/files#3). Записи, прикладывавшие файл, сами покажут
 * новое содержимое.
 */
export function ReplaceDialog({ file }: { file: FileCard }) {
  const [open, setOpen] = useState(false);
  const { t } = useTranslation('files');

  return (
    <Dialog
      open={open}
      onOpenChange={setOpen}
      title={t('replace.title', { name: file.name })}
      description={t('replace.intro')}
      closeLabel={t('close')}
      trigger={
        <Button tone="quiet" size="sm">
          {t('actions.replace')}
        </Button>
      }
    >
      <ReplaceForm file={file} onClose={() => setOpen(false)} />
    </Dialog>
  );
}

function ReplaceForm({ file, onClose }: { file: FileCard; onClose: () => void }) {
  const replace = useReplaceFile(file.id);
  const { t } = useTranslation('files');
  const [chosen, setChosen] = useState<File | null>(null);
  const [name, setName] = useState('');
  const [missing, setMissing] = useState(false);
  const failed = replace.error !== null && replace.error !== undefined;

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (chosen === null) {
      setMissing(true);
      return;
    }
    setMissing(false);
    replace.mutate({ file: chosen, name: name.trim() }, { onSuccess: onClose });
  }

  return (
    <form className="flex flex-col gap-4" onSubmit={submit} noValidate>
      <FileField
        fileLabel={t('replace.file')}
        nameLabel={t('replace.name')}
        nameHint={t('replace.nameHint')}
        name={name}
        onName={setName}
        onFile={(next) => {
          setChosen(next);
          setMissing(false);
        }}
        invalid={missing}
      />

      <div className="flex flex-wrap gap-2">
        <Button type="submit" disabled={replace.isPending}>
          {replace.isPending ? t('replace.pending') : t('replace.submit')}
        </Button>
        <Button tone="quiet" onClick={onClose}>
          {t('cancel')}
        </Button>
      </div>

      {failed ? <Callout tone="danger">{errorMessage(replace.error)}</Callout> : null}
    </form>
  );
}
