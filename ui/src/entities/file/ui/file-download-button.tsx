import { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { Button } from '@/shared/ui';
import { errorMessage } from '@/shared/errors';
import { fetchFileBlob, fileKeys, type FileCard } from '../api/files';
import { saveBlob } from '../model/save-blob';

/**
 * «Скачать»: байты читаются запросом с токеном и сохраняются браузером под именем файла.
 * Чтение — открытие файла для сервера. Отказ называется словами рядом с кнопкой, а не
 * молчит: ссылка с `download` на закрытый адрес просто не сработала бы.
 */
export function FileDownloadButton({ file }: { file: Pick<FileCard, 'id' | 'name'> }) {
  const { t } = useTranslation('files');
  const [pending, setPending] = useState(false);
  const [failure, setFailure] = useState<unknown>(null);
  const queryClient = useQueryClient();

  async function download() {
    setPending(true);
    setFailure(null);
    try {
      saveBlob(await fetchFileBlob(file.id), file.name);
      // Скачивание — открытие файла: «последний раз открыт» в списках устарело.
      await queryClient.invalidateQueries({ queryKey: fileKeys.lists });
    } catch (error) {
      setFailure(error);
    } finally {
      setPending(false);
    }
  }

  return (
    <>
      <Button tone="quiet" size="sm" disabled={pending} onClick={() => void download()}>
        {t('actions.download')}
      </Button>
      {failure === null ? null : (
        <span className="basis-full text-meta text-danger" role="alert">
          {errorMessage(failure)}
        </span>
      )}
    </>
  );
}
