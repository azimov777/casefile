import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  AuthorName,
  EntryCard,
  EntryHeadline,
  EntryKind,
  sectionEditsHeadline,
  type Entry,
} from '@/entities/entry';
import { RelativeTime } from '@/shared/ui';

interface SectionEditsGroupProps {
  first: number;
  last: number;
  entries: Entry[];
  checks: string[];
  /** Запись из адреса (`?entry=N`): если она в группе, группа раскрыта и запись помечена. */
  wanted: number | null;
}

/**
 * Правки разделов одного действия в ленте — одной строкой, а не семью парами
 * «было / стало» подряд (UI-133).
 *
 * Свёрнутая группа выглядит служебной записью: точка на нити, номера крайних записей,
 * «Правка разделов» с именами разделов, автор и время. Раскрытая показывает свои записи
 * обычными карточками, вложенными так же, как ответы под вопросом: сдвиг и полоса слева
 * говорят, что это части одной строки выше, а не соседи по ленте.
 *
 * Записи из дела не исчезают: у каждой свой `id="entry-N"`, и ссылка `TRK-106#8`
 * раскрывает группу и ведёт к записи 8. Раскрытие выводится из адреса **в том же
 * рендере**, а не эффектом: прокрутку к записи делает лента (`CasePage`) эффектом
 * на приход записи, и к тому моменту карточка обязана уже стоять в разметке.
 */
export function SectionEditsGroup({
  first,
  last,
  entries,
  checks,
  wanted,
}: SectionEditsGroupProps) {
  const { t } = useTranslation('ui');
  const holdsWanted = wanted !== null && entries.some((entry) => entry.no === wanted);

  /*
   * Выбор человека поверх адреса: `null` — «не трогал», тогда группа раскрыта ровно
   * тогда, когда в ней запись из адреса. Новый приход по ссылке в эту группу снимает
   * прежний выбор: человек, свернувший группу, а потом пришедший по ссылке на её
   * запись, должен эту запись увидеть. Правка состояния при рендере, а не эффектом, —
   * по той же причине, что выше.
   */
  const [choice, setChoice] = useState<boolean | null>(null);
  const [seenWanted, setSeenWanted] = useState(wanted);
  if (wanted !== seenWanted) {
    setSeenWanted(wanted);
    if (holdsWanted) setChoice(null);
  }
  const open = choice ?? holdsWanted;

  const [head] = entries;
  if (head === undefined) return null;
  const headline = sectionEditsHeadline(
    entries.map((entry) => (entry.type === 'section_changed' ? entry.payload.field : null)),
    t,
  );

  return (
    <section
      id={`group-${first}`}
      className="flex flex-col gap-2"
      aria-label={t('entry.group.label', { first, last })}
      data-group={head.action_id ?? undefined}
    >
      {/* Та же строка, что у служебной записи (`EntryCard`, `service`): поля, кегль и
          точка на нити — чтобы свёрнутая группа не выделялась среди соседей. */}
      <header className="flex flex-wrap items-center gap-3 px-4 py-1 text-meta text-muted">
        <span
          className="-ml-8 grid size-5 flex-none place-items-center rounded-pill border border-line-strong bg-surface"
          aria-hidden="true"
        >
          <EntryKind type={head.type} withName={false} />
        </span>
        <span className="font-mono font-bold text-text">
          #{t('entry.group.range', { first, last })}
        </span>
        <span className="text-text">
          <EntryHeadline headline={headline} />
        </span>
        <AuthorName author={head.author} />
        <RelativeTime value={head.created_at} />
        <button
          type="button"
          // Фон и цвет рамки названы явно — та же причина, что у копирования ссылки
          // в `EntryCard` (`docs/notes/ui.md`, «Кнопка без объявленного фона»).
          className="ml-auto border-none border-current bg-transparent p-0 text-label text-accent hover:underline"
          aria-expanded={open}
          onClick={() => setChoice(!open)}
        >
          {open ? t('entry.group.collapse') : t('entry.group.expand', { count: entries.length })}
        </button>
      </header>

      {open ? (
        <div className="ml-4 flex flex-col gap-2 border-l-2 border-l-line-strong pl-3">
          {entries.map((entry) => (
            <EntryCard
              key={entry.no}
              entry={entry}
              checks={checks}
              highlighted={wanted === entry.no}
            />
          ))}
        </div>
      ) : null}
    </section>
  );
}
