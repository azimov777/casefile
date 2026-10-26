import { useCallback, useRef, useState } from 'react';
import { uploadFile } from '../api/upload';
import type { FileCard } from '../api/files';

/** Сколько файлов принимает одна запись (контракт: `files`, не больше десяти). */
export const MAX_ATTACHMENTS = 10;

export interface Attachment {
  /** Ключ строки в форме, не id файла. */
  key: string;
  name: string;
  status: 'uploading' | 'ready' | 'failed';
  card?: FileCard;
  error?: unknown;
}

/**
 * Вложения формы записи. Файл уходит в проект сразу, как выбран (`POST /files`), и к записи
 * прикрепляется его id при отправке. Нагрузку считает сервер: размер, тип и предел —
 * его отказом, который строка вложения показывает словами (TRK#244).
 *
 * Загруженный, но снятый с формы файл остаётся в проекте — он виден на вкладке «Файлы»
 * как не приложенный ни к одной записи.
 */
export function useAttachments(project: string | null) {
  const [items, setItems] = useState<Attachment[]>([]);
  const counter = useRef(0);

  const add = useCallback(
    (files: File[]) => {
      if (project === null) return;
      for (const file of files) {
        counter.current += 1;
        const key = `${counter.current}-${file.name}`;
        setItems((all) => [...all, { key, name: file.name, status: 'uploading' }]);
        uploadFile({ project, file, name: '' }, crypto.randomUUID()).then(
          (card) =>
            setItems((all) =>
              all.map((it) => (it.key === key ? { ...it, status: 'ready', card } : it)),
            ),
          (error: unknown) =>
            setItems((all) =>
              all.map((it) => (it.key === key ? { ...it, status: 'failed', error } : it)),
            ),
        );
      }
    },
    [project],
  );

  const remove = useCallback(
    (key: string) => setItems((all) => all.filter((it) => it.key !== key)),
    [],
  );
  const reset = useCallback(() => setItems([]), []);

  const ids = items.flatMap((it) => (it.card === undefined ? [] : [it.card.id]));
  return {
    items,
    add,
    remove,
    reset,
    ids,
    uploading: items.some((it) => it.status === 'uploading'),
    full: items.length >= MAX_ATTACHMENTS,
  };
}

export type Attachments = ReturnType<typeof useAttachments>;
