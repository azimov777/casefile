import type { ComponentProps } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Link } from 'react-router';
import { splitTaskRefs, taskRefHref } from '../lib';
import styles from './markdown.module.css';

/**
 * Тело записи или раздел задачи в markdown.
 *
 * HTML из разметки не рисуется: `react-markdown` без `rehype-raw` выводит его как текст,
 * и это ровно то, что нужно — тела записей пишут агенты, а не редактор, которому доверяют.
 */
export function Markdown({ children }: { children: string }) {
  return (
    <div className={styles.markdown}>
      <ReactMarkdown remarkPlugins={[remarkGfm, remarkTaskRefs]} components={{ a: Anchor }}>
        {children}
      </ReactMarkdown>
    </div>
  );
}

/** Внутренняя ссылка идёт роутером, внешняя — обычной ссылкой в новую вкладку. */
function Anchor({ href, children }: ComponentProps<'a'>) {
  if (href !== undefined && href.startsWith('/')) return <Link to={href}>{children}</Link>;
  return (
    <a href={href} target="_blank" rel="noreferrer noopener">
      {children}
    </a>
  );
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
