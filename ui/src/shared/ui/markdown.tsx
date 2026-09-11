import type { ComponentProps } from 'react';
import ReactMarkdown, { type Components, type ExtraProps } from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Link } from 'react-router';
import { cn, splitTaskRefs, taskRefHref } from '../lib';

/**
 * Тело записи или раздел задачи в markdown.
 *
 * HTML из разметки не рисуется: `react-markdown` без `rehype-raw` выводит его как текст,
 * и это ровно то, что нужно — тела записей пишут агенты, а не редактор, которому доверяют.
 */
export function Markdown({ children }: { children: string }) {
  return (
    /*
     * Поля первого и последнего потомка гасятся вариантом по потомку, а не обёрткой:
     * «первый» и «последний» знает только родитель, а карте `components` видно лишь
     * то, каким узлом текст оказался, — какой абзац встанет первым, решает сама запись.
     */
    <div className="[&>:first-child]:mt-0 [&>:last-child]:mb-0">
      <ReactMarkdown remarkPlugins={[remarkGfm, remarkTaskRefs]} components={NODES}>
        {children}
      </ReactMarkdown>
    </div>
  );
}

/*
 * Утилиты чужому выводу раздаёт карта `components`: абзацы, списки, заголовки и ячейки
 * рисует `react-markdown` сам, своего `className` у них нет, и повесить утилиту
 * в разметке не на что.
 *
 * Карта и все обёртки объявлены на уровне модуля, а не в теле `Markdown`: собранные при
 * отрисовке, они были бы новыми по ссылке каждый раз, и React перемонтировал бы всё
 * поддерево разметки — а тело записи перерисовывается на каждом кадре живого потока.
 *
 * Плотность здесь — решение Д-серии UI-28, а не вкус: интервалы меньше типографских,
 * заголовок не крупнее строки. Классы, пришедшие из самой разметки (`language-ts`
 * у блока кода, `task-list-item` у пункта списка GFM), склеиваются с нашими и переживают
 * подмену: они единственный след того, чем узел был в тексте.
 */
const NODES = {
  a: Anchor,
  p: Paragraph,
  ul: UnorderedList,
  ol: OrderedList,
  pre: Preformatted,
  code: Code,
  blockquote: Quote,
  table: Table,
  th: HeadCell,
  td: Cell,
  h1: HeadingOne,
  h2: HeadingTwo,
  h3: HeadingThree,
  h4: HeadingFour,
} satisfies Components;

/** Заголовок разметки набран кеглем тела: внутри записи он метка раздела, а не голос. */
const HEADING = 'mt-3 mb-2 text-body font-bold';

/** Рамка у ячеек одна на обе роли: заголовок столбца отличается весом `<th>`, а не линией. */
const CELL = 'border border-line px-3 py-1 text-left';

/** Внутренняя ссылка идёт роутером, внешняя — обычной ссылкой в новую вкладку. */
function Anchor({ href, children }: ComponentProps<'a'>) {
  if (href !== undefined && href.startsWith('/')) return <Link to={href}>{children}</Link>;
  return (
    <a href={href} target="_blank" rel="noreferrer noopener">
      {children}
    </a>
  );
}

/*
 * `node` из пропсов вынимается и до элемента не доходит: `react-markdown` v10 передаёт
 * компоненту узел дерева разбора, и в DOM ему делать нечего — React выругался бы на
 * неизвестный атрибут.
 */
function Paragraph({ node: _node, className, ...rest }: ComponentProps<'p'> & ExtraProps) {
  return <p {...rest} className={cn('my-2', className)} />;
}

function UnorderedList({ node: _node, className, ...rest }: ComponentProps<'ul'> & ExtraProps) {
  return <ul {...rest} className={cn('my-2 pl-6', className)} />;
}

function OrderedList({ node: _node, className, ...rest }: ComponentProps<'ol'> & ExtraProps) {
  return <ol {...rest} className={cn('my-2 pl-6', className)} />;
}

/**
 * Блок кода гасит оформление своего `code` вариантом по потомку: сам `code` не знает,
 * стоит он в строке текста или в блоке, а фон и поля вокруг него в блоке уже нарисованы.
 */
function Preformatted({ node: _node, className, ...rest }: ComponentProps<'pre'> & ExtraProps) {
  return (
    <pre
      {...rest}
      className={cn(
        'my-2 overflow-x-auto rounded-mark bg-sunken p-3',
        '[&_code]:bg-transparent [&_code]:p-0',
        className,
      )}
    />
  );
}

function Code({ node: _node, className, ...rest }: ComponentProps<'code'> & ExtraProps) {
  return (
    <code {...rest} className={cn('rounded-mark bg-sunken px-1 font-mono text-meta', className)} />
  );
}

/**
 * Цвет назван только у левой границы (`border-l-line-strong`): у остальных трёх ширины
 * нет, и общий `border-line-strong` перекрасил бы то, чего не видно, — а замер
 * вычисленных стилей такую разницу видит.
 */
function Quote({ node: _node, className, ...rest }: ComponentProps<'blockquote'> & ExtraProps) {
  return (
    <blockquote
      {...rest}
      className={cn('my-2 border-l-2 border-l-line-strong pl-3 text-muted', className)}
    />
  );
}

function Table({ node: _node, className, ...rest }: ComponentProps<'table'> & ExtraProps) {
  return <table {...rest} className={cn('my-2 border-collapse', className)} />;
}

function HeadCell({ node: _node, className, ...rest }: ComponentProps<'th'> & ExtraProps) {
  return <th {...rest} className={cn(CELL, className)} />;
}

function Cell({ node: _node, className, ...rest }: ComponentProps<'td'> & ExtraProps) {
  return <td {...rest} className={cn(CELL, className)} />;
}

function HeadingOne({ node: _node, className, ...rest }: ComponentProps<'h1'> & ExtraProps) {
  return <h1 {...rest} className={cn(HEADING, className)} />;
}

function HeadingTwo({ node: _node, className, ...rest }: ComponentProps<'h2'> & ExtraProps) {
  return <h2 {...rest} className={cn(HEADING, className)} />;
}

function HeadingThree({ node: _node, className, ...rest }: ComponentProps<'h3'> & ExtraProps) {
  return <h3 {...rest} className={cn(HEADING, className)} />;
}

function HeadingFour({ node: _node, className, ...rest }: ComponentProps<'h4'> & ExtraProps) {
  return <h4 {...rest} className={cn(HEADING, className)} />;
}

/** Минимум узла разметки, которого хватает обходу: остальное плагину не нужно. */
interface MdastNode {
  type: string;
  value?: string;
  url?: string;
  children?: MdastNode[];
}

/**
 * Превращает `TRK-42` и `TRK-42#12` в тексте разметки в ссылки приложения.
 *
 * Плагин разбора, а не подмена готового html: до дерева ссылка — это текст внутри
 * абзаца, ячейки или пункта списка, и заменить его надо там же, где он стоит. После
 * дерева пришлось бы разбирать разметку второй раз и различать, где текст, а где код:
 * `TRK-42` внутри `code` ссылкой становиться не должен.
 */
function remarkTaskRefs() {
  return (tree: MdastNode) => {
    visit(tree);
  };
}

function visit(node: MdastNode): void {
  const children = node.children;
  if (children === undefined) return;

  // Ссылка внутри ссылки недопустима, а содержимое `code` и `inlineCode` — не текст,
  // и обход туда не заходит.
  if (node.type === 'link' || node.type === 'linkReference') return;

  const replaced: MdastNode[] = [];
  for (const child of children) {
    if (child.type !== 'text' || child.value === undefined) {
      visit(child);
      replaced.push(child);
      continue;
    }

    const parts = splitTaskRefs(child.value);
    if (parts.length === 1 && parts[0]?.kind === 'text') {
      replaced.push(child);
      continue;
    }

    for (const part of parts) {
      replaced.push(
        part.kind === 'text'
          ? { type: 'text', value: part.value }
          : {
              type: 'link',
              url: taskRefHref(part.ref),
              children: [{ type: 'text', value: part.value }],
            },
      );
    }
  }

  node.children = replaced;
}
