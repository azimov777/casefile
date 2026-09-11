import { useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { RelativeTime } from '@/shared/ui';
import { cn } from '@/shared/lib';
import type { Entry } from '../api/entries';
import { isServiceEntry } from '../api/entries';
import { entryHeadline, factsOfEntry } from '../model/headline';
import { AuthorName } from './author-name';
import { EntryBody } from './entry-body';
import { EntryHeadline } from './entry-headline';
import { EntryKind } from './entry-kind';

interface EntryCardProps {
  entry: Entry;
  /** Обзорные проверки задачи: вердикту нужен текст его проверки. */
  checks?: string[];
  /** Запись, на которую пришли по ссылке: её видно сразу и она подсвечена. */
  highlighted?: boolean;
  /** Ответы на вопрос: они живут под своим вопросом, а не отдельными записями ленты. */
  children?: ReactNode;
}

/**
 * Запись дела в ленте: шапка с номером, типом, автором и временем — и тело по типу.
 *
 * Ссылка на запись копируется в виде `TRK-42#12`: в этом виде её понимает и трекер,
 * и агент, которому человек её потом покажет, — в отличие от адреса страницы.
 */
export function EntryCard({ entry, checks, highlighted = false, children }: EntryCardProps) {
  const { t } = useTranslation('ui');
  const reference = `${entry.task_key}#${entry.no}`;
  const headline = entryHeadline(factsOfEntry(entry), entry.task_key, t);
  // Служебная запись несёт один факт и получает столько места, сколько в ней смысла:
  // строка вместо карточки. Прятать её нельзя — дело обязано быть полным.
  const service = isServiceEntry(entry.type);

  return (
    <article
      id={`entry-${entry.no}`}
      className={cn(
        'relative flex flex-col gap-2 rounded-control border border-line bg-surface px-4 py-3',
        // Ссылка ведёт под липкую шапку приложения, поэтому запись останавливается
        // ниже неё, а не под ней.
        'scroll-mt-[calc(var(--ui-header)+var(--spacing)*4)]',
        /*
         * Служебная запись несёт один факт, и места ей столько же: строка без рамки
         * карточки, с меньшими полями. Прятать её нельзя — дело обязано быть полным, —
         * но и занимать столько же, сколько сводка из четырёх частей, ей незачем.
         */
        service && 'gap-1 border-transparent bg-transparent py-1',
        // Запись, на которую пришли по ссылке: её надо найти глазами за долю секунды.
        // Обводка нарисована кольцом, а не второй рамкой: рамка сдвинула бы содержимое.
        // Видно её и на служебной записи — своей рамки у той нет.
        highlighted && 'border-accent ring-2 ring-accent',
      )}
      // Тип записи виден разметке, а не только глазу: сквозной тест меряет высоту
      // служебных записей, а искать их по тексту плашки значило бы завязаться на
      // подпись, которую завтра перепишут.
      data-type={entry.type}
      // Подсветка названа разметкой по той же причине: проверки спрашивают, помечена
      // ли именно та запись, на которую вела ссылка, а у утилиты имени нет — она
      // называет цвет рамки, а не «эту запись искали».
      data-highlighted={highlighted ? '' : undefined}
      aria-label={reference}
    >
      <header className="flex flex-wrap items-center gap-3 text-meta text-muted">
        {/*
         * Точка на нити времени: род записи виден до чтения слова (решение Д13).
         * Кружок поверхности с рамкой, чтобы линия под ним не просвечивала; знак
         * внутри — тот же, что в описи карточки: словарь родов один на всё приложение.
         *
         * Точка стоит в потоке шапки и выносится на нить отрицательным полем, а не
         * `absolute`. Абсолютный потомок, выступающий за низ короткой служебной записи,
         * увеличивал её `scrollHeight` — и сквозная проверка «ничего не спрятано
         * переполнением» считала запись обрезанной.
         */}
        <span
          className="-ml-8 grid size-5 flex-none place-items-center rounded-pill border border-line-strong bg-surface"
          aria-hidden="true"
        >
          <EntryKind type={entry.type} withName={false} />
        </span>
        <span className="font-mono font-bold text-text">#{entry.no}</span>
        <EntryKind type={entry.type} />
        {/* Заголовок служебной записи стоит прямо в шапке: отдельной строкой он был бы
            вторым разом сказанным одним и тем же — и потому читается её продолжением,
            в цвете содержания, а не служебной подписи. */}
        {service && headline.kind === 'built' ? (
          <span className="text-text">
            <EntryHeadline headline={headline} />
          </span>
        ) : null}
        <AuthorName author={entry.author} />
        <RelativeTime value={entry.created_at} />
        <CopyReference reference={reference} />
      </header>

      {/*
       * Чей заголовок — решает `entryHeadline`. У записи агента он написан автором;
       * у `answer` и `verdict` его выводит трекер по-английски, и здесь он собирается
       * заново по-русски; у сводки он дословно повторяет «следующий шаг» из тела,
       * и второй раз его показывать незачем.
       */}
      {service ? null : headline.kind === 'built' ? (
        <h3 className="text-body font-semibold">
          <EntryHeadline headline={headline} />
        </h3>
      ) : headline.kind === 'author' ? (
        <h3 className="text-body font-semibold">{entry.title}</h3>
      ) : null}

      <EntryBody entry={entry} checks={checks} />

      {children}
    </article>
  );
}

/**
 * Копирование ссылки. Буфер обмена есть не всегда: браузер даёт его только в защищённом
 * контексте и может отказать по правам — поэтому отказ показывается, а не проглатывается.
 *
 * Стоит ссылка справа и на одном месте в каждой строке (решение Д15): её копируют,
 * чтобы сослаться из другой задачи, и искать её глазами каждый раз заново — работа,
 * которой быть не должно.
 */
function CopyReference({ reference }: { reference: string }) {
  const { t } = useTranslation('ui');
  const [state, setState] = useState<'idle' | 'done' | 'failed'>('idle');

  async function copy() {
    try {
      await navigator.clipboard.writeText(reference);
      setState('done');
    } catch {
      setState('failed');
    }
  }

  return (
    <span className="ml-auto inline-flex shrink-0 items-center gap-2">
      <button
        type="button"
        /*
         * Фон назван явно: у кнопки без `background` браузер рисует свой `ButtonFace`,
         * и текст на нём не добирает контраста (`docs/notes/ui.md`). Цвет рамки —
         * тоже: `border-none` снимает только начертание, а цвет оставляет браузеру
         * (`buttontext`), тогда как сокращение `border: none` возвращало его к
         * `currentColor`. Рамки не видно ни там ни там, но замер вычисленных стилей
         * видит разницу — и следующий перевод начнётся с разбора этих трёх строк.
         */
        className="border-none border-current bg-transparent p-0 font-mono text-label text-muted hover:text-text hover:underline"
        onClick={() => void copy()}
      >
        {t('entry.copy', { reference })}
      </button>
      {state === 'idle' ? null : (
        <span className="text-label" role="status">
          {state === 'done' ? t('entry.copied') : t('entry.clipboardUnavailable')}
        </span>
      )}
    </span>
  );
}
