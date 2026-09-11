import { cva } from 'class-variance-authority';
import type { ReactNode } from 'react';

/**
 * Тон плашки: положение дел, а не сущность. Поэтому `positive` носит и статус
 * `done`, и удачный вердикт, а `danger` — и блокировку, и `critical`.
 *
 * Тонов ровно шесть, по числу различимых положений: цвет на каждую сущность
 * превратил бы список в радугу, в которой не читается ничего. Цвета живут
 * в `tokens.css` — здесь только имена.
 */
export type BadgeTone = 'neutral' | 'progress' | 'positive' | 'dropped' | 'attention' | 'danger';

/*
 * Варианты собраны `cva` по образцу кнопки, но склейки `cn` здесь нет: внешнего
 * `className` плашка не принимает, и мирить с ним нечего — `cva` отдаёт готовую
 * строку прямо в атрибут.
 */
const badge = cva(
  [
    /*
     * Метка сжимается и обрезается многоточием (`truncate`), а не выталкивает соседей
     * за край ячейки. Без `min-w-0` элемент гибкой раскладки не становится уже своего
     * содержимого, и длинное значение уносило соседей по строке за правый край —
     * поймано на снятой с тех пор колонке тегов, но правило от неё не зависело.
     */
    'inline-block min-w-0 max-w-full truncate',
    'rounded-mark border px-2 text-label leading-[1.6]',
  ],
  {
    variants: {
      /*
       * Тон меняет три вещи разом: заливку, границу и текст. Меньше нельзя — текст,
       * оставленный от нейтрального тона, не прошёл бы контраст на чужой заливке.
       *
       * Прозрачности ни в одном тоне нет намеренно. `opacity` смешивает цвет текста
       * с заливкой плашки, и контраст падает ниже AA: замерено `axe` на карточке
       * задачи. Тоны подобраны так, что текст на своей заливке ровно проходит порог,
       * — приглушать его нечем (`docs/notes/ui.md`, «Прозрачность поверх цветной
       * поверхности — риск для контраста»).
       */
      tone: {
        neutral: 'border-neutral-line bg-neutral-soft text-neutral',
        progress: 'border-progress-line bg-progress-soft text-progress',
        positive: 'border-positive-line bg-positive-soft text-positive',
        /*
         * Снятое ничем не занято, и это видно без цвета: заливки нет, граница
         * пунктиром. Различие держится и на чёрно-белом экране, и у человека,
         * не различающего цвета.
         */
        dropped: 'border-dashed border-dropped-line bg-transparent text-dropped',
        attention: 'border-attention-line bg-attention-soft text-attention',
        danger: 'border-danger-line bg-danger-soft text-danger',
      },
      /** Моноширинный: идентификатор из контракта, а не подпись (`CONVENTIONS.md`). */
      mono: { true: 'font-mono', false: '' },
    },
    defaultVariants: { tone: 'neutral', mono: false },
  },
);

interface BadgeProps {
  /** Нейтральный по умолчанию: плашка без своего положения дел (тег, исполнитель). */
  tone?: BadgeTone;
  /**
   * Род значения: «статус», «приоритет», «тег». Пишется внутри плашки мелким и
   * приглушённым — и потому попадает в её доступное имя.
   *
   * Подпись именно внутри, а не рядом: рядом стоящая подпись читалась бы диктору
   * отдельной строкой, а плашка осталась бы просто словом `open`. Четыре плашки
   * подряд без родов — `open`, `normal`, `demo_agent`, `retention` — не читаются
   * ни глазами, ни на слух.
   */
  kind?: string;
  /** Моноширинный: идентификатор из контракта, а не подпись (`CONVENTIONS.md`). */
  mono?: boolean;
  title?: string;
  children: ReactNode;
}

/**
 * Короткая метка в строке таблицы: статус, приоритет, тег, признак.
 *
 * Цвет не единственный носитель смысла: подпись внутри плашки остаётся всегда
 * (`CONCEPT.md`, 6) — тон только позволяет просканировать список взглядом,
 * не читая каждую строку.
 */
export function Badge({ tone = 'neutral', kind, mono = false, title, children }: BadgeProps) {
  return (
    <span data-badge={tone} className={badge({ tone, mono })} title={title}>
      {kind === undefined ? null : (
        /*
         * Род значения внутри плашки. Моноширинность на него не распространяется:
         * это подпись, а не идентификатор контракта (`CONCEPT.md`, 6), — и различаются
         * они гарнитурой, а не приглушённостью.
         */
        <span className="font-sans text-label font-normal">{kind} </span>
      )}
      {children}
    </span>
  );
}
