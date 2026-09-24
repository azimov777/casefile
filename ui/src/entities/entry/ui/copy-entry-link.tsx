import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Check, Link2 } from 'lucide-react';
import { entryAddress } from '../model/address';

/**
 * Кнопка «скопировать ссылку на запись»: кладёт в буфер адрес, который открывается в
 * браузере (`entryAddress`), — в отличие от `KEY#N`, который понимают трекер и агент
 * (UI-155). Стоит и в описи карточки, и в ленте дела.
 *
 * Знак, а не слово: в описи кнопка живёт в узкой ячейке номера, и подпись раздвинула
 * бы столбец у каждой строки. Имя для диктора и голосового управления — в
 * `aria-label`, подсказка мыши — в `title`; сама кнопка видна всегда, без наведения
 * (UI-153), и на телефоне держит мишень в 24 px (UI-154).
 *
 * Исход виден тут же: удача меняет знак на галочку и объявляется вежливо, отказ буфера
 * сказан словами — молча не скопированную ссылку человек вставил бы старой.
 */
export function CopyEntryLink({ taskKey, no }: { taskKey: string; no: number }) {
  const { t } = useTranslation('ui');
  const [state, setState] = useState<'idle' | 'done' | 'failed'>('idle');

  async function copy() {
    try {
      // На незащищённой странице `navigator.clipboard` нет вовсе: это тот же отказ.
      if (navigator.clipboard === undefined) throw new Error('Clipboard is not available');
      await navigator.clipboard.writeText(entryAddress(taskKey, no, window.location.origin));
      setState('done');
    } catch {
      setState('failed');
    }
  }

  const label = t('entry.copyLink', { no });
  const Mark = state === 'done' ? Check : Link2;

  return (
    <span className="inline-flex items-center gap-1 align-middle">
      <button
        type="button"
        // Фон и цвет рамки названы явно — та же причина, что у `CopyReference`
        // (`docs/notes/ui.md`, «Кнопка без объявленного фона»).
        className="inline-grid cursor-pointer place-items-center rounded-mark border-none border-current bg-transparent p-0 text-muted max-fold:min-h-(--ui-tap) max-fold:min-w-(--ui-tap) hover:text-text focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus"
        aria-label={label}
        title={label}
        data-copy-link={no}
        onClick={() => void copy()}
      >
        <Mark className="size-(--ui-mark)" aria-hidden="true" />
      </button>
      <span className={state === 'failed' ? 'text-label' : 'sr-only'} role="status">
        {state === 'done'
          ? t('entry.linkCopied')
          : state === 'failed'
            ? t('entry.clipboardUnavailable')
            : ''}
      </span>
    </span>
  );
}
