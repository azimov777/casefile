import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Button, Dialog } from '@/shared/ui';
import type { FileCard } from '../api/files';
import { FileImage } from './file-image';

/**
 * «Открыть» для изображения: окно с картинкой. Байты читаются, только когда окно открыто
 * (содержимое окна рождается на каждый заход), поэтому список с сотней изображений не
 * открывает ни одного из них.
 */
export function FileImageDialog({ file }: { file: Pick<FileCard, 'id' | 'name'> }) {
  const [open, setOpen] = useState(false);
  const { t } = useTranslation('files');

  return (
    <Dialog
      open={open}
      onOpenChange={setOpen}
      title={t('preview.title', { name: file.name })}
      description={t('preview.intro')}
      closeLabel={t('close')}
      trigger={
        <Button tone="quiet" size="sm">
          {t('actions.open')}
        </Button>
      }
    >
      <FileImage file={file} className="max-h-[70vh] max-w-full self-start object-contain" />
    </Dialog>
  );
}
