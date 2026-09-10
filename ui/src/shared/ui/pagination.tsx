import { ChevronLeft, ChevronRight } from 'lucide-react';
import { Link } from 'react-router';
import type { ReactNode } from 'react';
import { cn } from '../lib';

/*
 * Пагинация на shadcn/ui: разметка, роли и `aria-current` взяты у неё, оформление
 * переписано на наши токены, а подписи — на русский. Своего состояния у неё нет
 * и быть не может: номер страницы живёт в адресе, и каждая кнопка ряда — ссылка
 * на этот адрес. Отсюда и `Link` вместо `<a>`: переход внутри приложения, а не
 * перезагрузка страницы.
 *
 * Кнопкой номер страницы делать нельзя: по ссылке видно, куда она ведёт, её открывают
 * в новой вкладке и пересылают, а «назад» после перехода возвращает на прежнюю
 * страницу выдачи — всё это человек ждёт от списка и ничего из этого кнопка не даёт.
 */

/**
 * Ячейка ряда: квадрат под однозначный номер, растущий вширь под двузначный.
 *
 * `no-underline` обязателен: у ссылки подчёркивание от браузера, а подчёркнутая цифра
 * в рамке читается как ошибка вёрстки, а не как переход. Так же поступает и
 * переключатель вида — единственное другое место, где ссылка выглядит кнопкой.
 */
const CELL = [
  'inline-flex h-7 min-w-7 items-center justify-center gap-1 rounded-mark px-1.5',
  'text-mark leading-none no-underline',
  'transition-colors duration-(--motion-fast) ease-fast',
  'focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus',
];

export function Pagination({ children, label }: { children: ReactNode; label: string }) {
  return (
    <nav aria-label={label}>
      {/*
       * Список, а не набор ссылок подряд: диктор объявляет его длину, и человек
       * слышит, сколько ступеней в ряду, не обходя их. `list-none` при этом
       * обязателен — своего сброса списков у проекта нет, и браузер поставил бы
       * перед каждой ступенью маркер.
       */}
      <ul className="flex list-none flex-wrap items-center gap-1">{children}</ul>
    </nav>
  );
}

export function PaginationItem({ children }: { children: ReactNode }) {
  return <li>{children}</li>;
}

interface PaginationLinkProps {
  to: string;
  /** Эта страница открыта сейчас: диктор узнаёт об этом из `aria-current`. */
  current?: boolean;
  /** Что читает диктор, если сама подпись — знак: «Предыдущая страница». */
  label?: string;
  children: ReactNode;
}

export function PaginationLink({ to, current = false, label, children }: PaginationLinkProps) {
  return (
    <Link
      to={to}
      aria-label={label}
      // `page`, а не `true`: здесь это буквально текущая страница выдачи, ровно тот
      // случай, под который значение и заведено.
      aria-current={current ? 'page' : undefined}
      className={cn(
        CELL,
        current
          ? 'bg-accent font-medium text-accent-text'
          : 'border border-line-strong text-text hover:bg-sunken',
      )}
    >
      {children}
    </Link>
  );
}

/**
 * Ступенька ряда, которой некуда вести: у первой страницы нет предыдущей.
 *
 * Место она занимает по-прежнему — иначе ряд сдвигался бы вбок на каждом переходе,
 * и человек промахивался бы по кнопке, на которую только что смотрел.
 *
 * Запрещённая кнопка, а не приглушённая ссылка: ссылки без адреса не бывает, а имя
 * (`aria-label`) на `span` или на `a` без `href` — нарушение, которое ловит `axe`
 * (`aria-prohibited-attr`): у обоих нет роли, которой имя позволено. Запрет выражен
 * заливкой из токенов и атрибутом `disabled`, как у любой другой кнопки проекта.
 */
export function PaginationStub({ label, children }: { label: string; children: ReactNode }) {
  return (
    <button
      type="button"
      disabled
      aria-label={label}
      className={cn(CELL, 'border border-line bg-sunken text-muted')}
    >
      {children}
    </button>
  );
}

/** Шаг назад и шаг вперёд: знаком, потому что подпись словами занимает полряда. */
export function PaginationPrevious({ to, label }: { to: string | null; label: string }) {
  const arrow = <ChevronLeft className="size-(--ui-mark)" aria-hidden="true" />;
  return to === null ? (
    <PaginationStub label={label}>{arrow}</PaginationStub>
  ) : (
    <PaginationLink to={to} label={label}>
      {arrow}
    </PaginationLink>
  );
}

export function PaginationNext({ to, label }: { to: string | null; label: string }) {
  const arrow = <ChevronRight className="size-(--ui-mark)" aria-hidden="true" />;
  return to === null ? (
    <PaginationStub label={label}>{arrow}</PaginationStub>
  ) : (
    <PaginationLink to={to} label={label}>
      {arrow}
    </PaginationLink>
  );
}

/**
 * Пропуск в ряду номеров. Своё место в списке прячет от диктора целиком: пустой пункт
 * он объявил бы наравне со ссылками, а сказать ему многоточие ничего не может.
 */
export function PaginationGap() {
  return (
    <li
      aria-hidden="true"
      className="inline-flex h-7 min-w-5 items-center justify-center text-faint"
    >
      …
    </li>
  );
}
