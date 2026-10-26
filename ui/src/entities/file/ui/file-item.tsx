import type { ReactNode } from 'react';
import { FileText } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { Badge, RelativeTime } from '@/shared/ui';
import { cn } from '@/shared/lib';
import type { FileCard } from '../api/files';
import { useFormatBytes } from '../model/format-bytes';

/**
 * Один файл карточкой: имя, проект и тип, размер, кто и когда добавил, когда последний раз
 * открыт, сколько записей и задач на него ссылаются. Выбор и действия приходят слотами:
 * показывает их тот, кому они разрешены (недоступное не показывается, TRK/ui-screens#2).
 *
 * Карточкой, а не строкой таблицы, — по той же причине, что строки доступов и людей: на
 * 390 px таблица либо уезжает вбок, либо схлопывает столбцы, а карточка переносит своё
 * содержимое сама. Байтов карточка не читает никогда (`fetchFileBlob`).
 *
 * Ничего не вычисляет: размер, время открытия и число ссылок приходят в карточке.
 */
export function FileItem({
  file,
  select,
  actions,
  archived = false,
}: {
  file: FileCard;
  /** Флажок выбора слева; `undefined` — выбрать нельзя. */
  select?: ReactNode;
  /** Что с файлом можно сделать. */
  actions?: ReactNode;
  /** Проект файла в архиве: он заморожен, и карточка говорит об этом словами. */
  archived?: boolean;
}) {
  const { t } = useTranslation('files');
  const formatBytes = useFormatBytes();
  const added = file.added_by.signature ?? null;
  const replaced = file.replaced_by?.signature ?? null;

  return (
    <article
      aria-label={t('item.label', { name: file.name })}
      data-file={file.id}
      className={cn(
        'flex min-w-0 flex-wrap items-start gap-x-3 gap-y-2 rounded-control border border-line p-3',
        archived ? 'bg-sunken' : 'bg-surface',
      )}
    >
      {select === undefined ? null : (
        <div className="flex min-h-(--ui-tap) items-center">{select}</div>
      )}

      <FileText className="mt-0.5 size-(--ui-mark) shrink-0 text-faint" aria-hidden="true" />

      <div className="flex min-w-0 flex-1 basis-60 flex-col gap-1">
        <p className="flex flex-wrap items-center gap-2">
          {/* Имя вписал человек или агент: это данные, длинное переносим. */}
          <span data-role="name" className="font-medium wrap-anywhere text-text">
            {file.name}
          </span>
          <Badge tone="neutral">{file.project_key}</Badge>
          {file.unopened === true ? (
            <span data-role="unopened">
              <Badge tone="attention">{t('item.unopened')}</Badge>
            </span>
          ) : null}
          {archived ? <Badge tone="dropped">{t('item.archived')}</Badge> : null}
        </p>

        <p className="flex flex-wrap items-center gap-x-3 gap-y-1 text-meta text-muted">
          <span data-role="type" className="font-mono wrap-anywhere">
            {file.mime_type}
          </span>
          <span data-role="size">{formatBytes(file.size_bytes)}</span>
          <span data-role="added">
            {added === null ? t('item.addedByTracker') : t('item.addedBy', { author: added })}{' '}
            <RelativeTime value={file.added_at} />
          </span>
          <span data-role="opened">
            {file.last_opened_at === null || file.last_opened_at === undefined ? (
              t('item.neverOpened')
            ) : (
              <>
                {t('item.opened')} <RelativeTime value={file.last_opened_at} />
              </>
            )}
          </span>
          {file.replaced_at === null || file.replaced_at === undefined ? null : (
            <span data-role="replaced">
              {replaced === null
                ? t('item.replacedByTracker')
                : t('item.replaced', { author: replaced })}{' '}
              <RelativeTime value={file.replaced_at} />
            </span>
          )}
          <span data-role="refs">
            {file.entries === 0
              ? t('item.noRefs')
              : t('item.refs', { count: file.entries, tasks: file.tasks })}
          </span>
        </p>
      </div>

      {actions === undefined ? null : (
        <div className="flex flex-wrap items-center gap-2">{actions}</div>
      )}
    </article>
  );
}
