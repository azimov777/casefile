import { createContext, useContext, type ReactNode } from 'react';
import { Link, type LinkProps } from 'react-router';
import { cn } from '../lib';
import { controlSize, type ControlSize } from './control-size';

/*
 * Переключатель вида: несколько видов одного и того же — «Карточка / Дело», «Таблица /
 * Доска» — одной дорожкой, текущий вид поднят на ней плашкой.
 *
 * Ссылки, а не `ToggleGroup` из shadcn/ui. Там кнопки Radix с ролью `radio` и
 * `aria-checked`: смена вида стала бы выбором внутри формы, которой нет, — адрес не
 * виден в строке состояния, вид не открыть в новой вкладке, и роль ссылки для диктора
 * пропадает. Вид живёт в адресе, значит его смена — переход (`docs/notes/ui.md`,
 * «Переключатель вида — это переход, а не форма»), и «назад» браузера возвращает
 * прежний вид ровно потому, что это обычная навигация `react-router`.
 *
 * Высота дорожки — та же шкала, что у `Button` (`control-size.ts`): переключатель
 * и кнопка одного `size` одной высоты и в строке стоят вровень.
 */

const SizeContext = createContext<ControlSize>('md');

interface SegmentedNavProps {
  /** Имя ориентира: что именно переключается («Вид списка», «Вид задачи»). */
  label: string;
  size?: ControlSize;
  children: ReactNode;
  className?: string;
}

/** Дорожка переключателя: ориентир `nav` с именем, в нём ссылки `SegmentedNavLink`. */
export function SegmentedNav({ label, size = 'md', children, className }: SegmentedNavProps) {
  return (
    <SizeContext value={size}>
      <nav
        aria-label={label}
        className={cn(
          // Рамка и поле входят в минимум высоты: `box-sizing: border-box`, поэтому
          // дорожка ровно той же высоты, что и кнопка её размера.
          'inline-flex items-stretch gap-px rounded-control border border-line bg-sunken p-px',
          controlSize[size],
          className,
        )}
      >
        {children}
      </nav>
    </SizeContext>
  );
}

interface SegmentedNavLinkProps extends Omit<LinkProps, 'className' | 'aria-current'> {
  /**
   * Текущий ли это вид и каким словом сказать это диктору: `page` — виды живут на
   * разных страницах (карточка и дело), `true` — одна страница в разном виде (таблица
   * и доска списка). `false` — не текущий.
   */
  current: 'page' | 'true' | false;
}

/** Один вид на дорожке. Адрес и состояние перехода — как у обычной `Link`. */
export function SegmentedNavLink({ current, children, ...rest }: SegmentedNavLinkProps) {
  const size = useContext(SizeContext);

  return (
    <Link
      {...rest}
      aria-current={current === false ? undefined : current}
      className={cn(
        'inline-flex items-center justify-center rounded-[calc(var(--radius-control)-2px)] leading-[1.2] no-underline',
        size === 'sm' ? 'px-2.5' : 'px-3.5',
        // Отклик на наведение — единственное движение, которое переключателю позволено.
        'transition-colors duration-(--motion-fast) ease-fast',
        'focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus',
        // Текущий вид — плашка поверхности на утопленной дорожке, как у переключателя
        // системы, а не заливка акцентом: акцент в строке принадлежит главному
        // действию, и два акцентных пятна рядом читались бы двумя кнопками.
        current === false
          ? 'text-muted hover:text-text'
          : 'bg-surface font-semibold text-text shadow-raised',
      )}
    >
      {/*
       * Место под жирное начертание держит невидимый дубль подписи в той же ячейке
       * сетки (UI-144). Текущий сегмент набран жирным, а жирное шире: без дубля ширина
       * сегмента зависела бы от того, текущий ли он, и дорожка «Карточка / Дело» на
       * двух страницах была бы разной ширины — переключатель ездил бы под курсором на
       * доли пикселя. Дубль скрыт и от диктора (`aria-hidden`), и от глаза (`invisible`):
       * имя ссылки остаётся одним словом.
       */}
      <span className="inline-grid">
        <span className="col-start-1 row-start-1 inline-flex items-center justify-center">
          {children}
        </span>
        <span
          className="invisible col-start-1 row-start-1 inline-flex items-center justify-center font-semibold"
          aria-hidden="true"
        >
          {children}
        </span>
      </span>
    </Link>
  );
}
