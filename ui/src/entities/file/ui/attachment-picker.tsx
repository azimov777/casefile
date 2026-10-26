import { useId, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/shared/ui';
import { errorMessage } from '@/shared/errors';
import { MAX_ATTACHMENTS, type Attachments } from '../model/use-attachments';
import { useFormatBytes } from '../model/format-bytes';

/**
 * Выбор файлов к записи: кнопка «Прикрепить файл» и строки выбранных со статусом загрузки.
 * Стоит под кнопками формы (всё, что растёт, стоит ниже кнопки отправки, TRK/ui-screens#21).
 */
export function AttachmentPicker({ attachments }: { attachments: Attachments }) {
  const { t } = useTranslation('files');
  const formatBytes = useFormatBytes();
  const input = useRef<HTMLInputElement>(null);
  const labelId = useId();

  return (
    <div className="flex flex-col gap-2" role="group" aria-labelledby={labelId}>
      <div className="flex flex-wrap items-center gap-2">
        <span id={labelId} className="text-meta text-muted">
          {t('attach.label')}
        </span>
        <Button
          type="button"
          tone="quiet"
          size="sm"
          disabled={attachments.full}
          onClick={() => input.current?.click()}
        >
          {t('attach.pick')}
        </Button>
        <input
          ref={input}
          type="file"
          multiple
          hidden
          aria-label={t('attach.input')}
          data-attach-input=""
          onChange={(event) => {
            attachments.add(Array.from(event.target.files ?? []));
            event.target.value = '';
          }}
        />
        {attachments.full ? (
          <span className="text-meta text-muted">{t('attach.full', { max: MAX_ATTACHMENTS })}</span>
        ) : null}
      </div>
      {attachments.items.length === 0 ? null : (
        <ul className="flex list-none flex-col gap-1 p-0">
          {attachments.items.map((item) => (
            <li
              key={item.key}
              data-attachment={item.status}
              className="flex flex-wrap items-center gap-x-3 gap-y-1 text-meta"
            >
              <span className="font-medium wrap-anywhere text-text">{item.name}</span>
              {item.status === 'uploading' ? (
                <span className="text-muted" role="status">
                  {t('attach.uploading')}
                </span>
              ) : null}
              {item.status === 'ready' && item.card !== undefined ? (
                <span className="text-muted">{formatBytes(item.card.size_bytes)}</span>
              ) : null}
              {item.status === 'failed' ? (
                <span className="text-danger" role="alert">
                  {errorMessage(item.error)}
                </span>
              ) : null}
              <Button
                type="button"
                tone="quiet"
                size="sm"
                aria-label={t('attach.remove', { name: item.name })}
                onClick={() => attachments.remove(item.key)}
              >
                {t('attach.removeShort')}
              </Button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
