import { useTranslation } from 'react-i18next';
import { Callout } from '@/shared/ui';
import { errorMessage } from '@/shared/errors';
import { useFileObjectUrl } from '../model/use-file-object-url';
import type { FileCard } from '../api/files';

/**
 * Изображение файла из установки. Байты читаются запросом с токеном и показываются через
 * `blob:`-адрес — `<img src>` заголовка `Authorization` не несёт. Чтение — открытие файла
 * для сервера, поэтому компонент ставят только там, где человек сам попросил увидеть
 * картинку, а не в каждой строке списка.
 */
export function FileImage({
  file,
  className,
}: {
  file: Pick<FileCard, 'id' | 'name'>;
  className?: string;
}) {
  const { t } = useTranslation('files');
  const { url, query } = useFileObjectUrl(file.id, true);

  if (query.error !== null && query.error !== undefined) {
    return <Callout tone="danger">{errorMessage(query.error)}</Callout>;
  }
  if (url === null) return <Callout>{t('preview.loading')}</Callout>;

  return <img src={url} alt={t('preview.alt', { name: file.name })} className={className} />;
}
