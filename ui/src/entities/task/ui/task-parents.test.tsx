import { useEffect, type ReactNode } from 'react';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router';
import userEvent from '@testing-library/user-event';
import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { task } from '@testing/msw/responses';
import { say } from '@testing/say';
import type { Task } from '../api/tasks';
import { ParentPanel } from './parent-badge';
import { TaskCard } from './task-card';
import { TaskRow } from './task-row';

/** Родитель с названием, которое не влезает в столбец доски ни на одной ширине. */
const PROGRAM = {
  key: 'DEMO-2',
  title:
    'Лента журнала теряет записи при переподключении: src/features/live-journal/model/frames.ts',
};
const SECOND = { key: 'DEMO-8', title: 'Доставка журнала без потерь' };

/** Где оказался маршрутизатор: переход по ссылке виден только так. */
const where = { current: '' };

function Probe() {
  const location = useLocation();
  useEffect(() => {
    where.current = location.pathname;
  }, [location]);
  return null;
}

/** Рисует представление задачи на маршруте списка: так же, как его видит человек. */
function show(view: ReactNode) {
  where.current = '/tasks';
  return render(
    <MemoryRouter initialEntries={['/tasks?queue=DEMO']}>
      <Probe />
      <Routes>
        <Route path="/tasks" element={view} />
        <Route path="/tasks/:key" element={null} />
      </Routes>
    </MemoryRouter>,
  );
}

function card(row: Task) {
  return show(<TaskCard task={row} />);
}

function tableRow(row: Task, parentSlot = false) {
  return show(
    <table>
      <tbody>
        <TaskRow task={row} parentSlot={parentSlot} />
      </tbody>
    </table>,
  );
}

/** Подпись родителя — узел с меткой: у задачи верхнего уровня его нет вовсе. */
function caption(container: HTMLElement): HTMLElement | null {
  return container.querySelector('[data-mark="parents"]');
}

describe('карточка доски называет родителя', () => {
  it('у задачи верхнего уровня подписи нет, и ссылка на карточке одна', () => {
    const { container } = card(task('DEMO-3', { parents: [] }));

    expect(caption(container)).toBeNull();
    expect(screen.getAllByRole('link')).toHaveLength(1);
    expect(screen.getByRole('link')).toHaveAttribute('href', '/tasks/DEMO-3');
    // Ни пустой строки, ни заглушки: первым в карточке стоит ряд ключа, как до UI-119.
    expect(container.querySelector('article')?.firstElementChild).toHaveTextContent('DEMO-3');
  });

  it('поле, которого в строке нет, читается как «родителя нет», а не падает', () => {
    const row = task('DEMO-3');
    delete row.parents;
    const { container } = card(row);

    expect(caption(container)).toBeNull();
  });

  it('родитель стоит первой строкой, над ключом, ключом и названием, ссылкой в него', () => {
    const { container } = card(task('DEMO-5', { parents: [PROGRAM] }));

    const shown = caption(container);
    expect(shown).not.toBeNull();
    expect(container.querySelector('article')?.firstElementChild).toBe(shown);

    const link = within(shown as HTMLElement).getByRole('link');
    expect(link).toHaveAttribute('href', '/tasks/DEMO-2');
    // Род назван диктору: иначе ключ чужой задачи читался бы как ключ этой.
    expect(link).toHaveAccessibleName(
      `${say.ui('task.parents.label')} ${say.ui('task.parents.item', PROGRAM)}`,
    );
    // Одна строка с многоточием, полный текст — подсказкой.
    expect(link).toHaveClass('truncate', 'min-w-0');
    // Переноса на узком месте у карточки доски нет: она держит одну строку (UI-115).
    expect(link).not.toHaveClass('@max-list:whitespace-normal');
    expect(link).toHaveAttribute('title', say.ui('task.parents.item', PROGRAM));
    // Ключ — идентификатор контракта: моноширинным, как всюду.
    expect(within(link).getByText('DEMO-2')).toHaveClass('font-mono');

    // Ссылка в саму задачу на месте и по-прежнему одна.
    const own = screen.getAllByRole('link').filter((node) => node !== link);
    expect(own).toHaveLength(1);
    expect(own[0]).toHaveAttribute('href', '/tasks/DEMO-5');
  });

  it('ссылка на родителя поднята над растяжкой и ведёт в родителя, а не в задачу', async () => {
    const user = userEvent.setup();
    const { container } = card(task('DEMO-5', { parents: [PROGRAM] }));

    const link = within(caption(container) as HTMLElement).getByRole('link');
    // Растяжка карточки — `after:absolute` у ссылки названия; всё, что стоит над ней,
    // поднято `relative z-1`. Поднята ссылка, а не строка целиком: пустое место справа
    // от короткой подписи остаётся мишенью задачи.
    expect(link).toHaveClass('relative', 'z-1');
    expect(caption(container)).not.toHaveClass('relative');

    await user.click(link);
    expect(where.current).toBe('/tasks/DEMO-2');
  });

  it('двух родителей не прячет: первый ссылкой, остальные числом и поимённо', () => {
    const { container } = card(task('DEMO-5', { parents: [PROGRAM, SECOND] }));

    const shown = caption(container) as HTMLElement;
    const links = within(shown).getAllByRole('link');
    // Ссылкой — первый по порядку связи, как он стоит первым среди `child` в карточке.
    expect(links).toHaveLength(1);
    expect(links[0]).toHaveAttribute('href', '/tasks/DEMO-2');

    // Число остальных видно всегда, и глазом, и диктором — вместе с именами.
    expect(shown).toHaveTextContent(say.ui('task.parents.more', { count: 1 }));
    expect(
      within(shown).getByText(
        say.ui('task.parents.others', {
          count: 1,
          parents: [say.ui('task.parents.item', SECOND)],
        }),
      ),
    ).toHaveClass('sr-only');

    // Подсказка у ссылки и у числа одна и та же: все родители, по одному на строку.
    const everyone = [PROGRAM, SECOND].map((item) => say.ui('task.parents.item', item)).join('\n');
    expect(links[0]).toHaveAttribute('title', everyone);
    const more = within(shown).getByText(say.ui('task.parents.more', { count: 1 }));
    expect(more.parentElement).toHaveAttribute('title', everyone);
    // Число не усекается: многоточие съедает название первого, а не сведения о втором.
    expect(more.parentElement).toHaveClass('shrink-0', 'relative', 'z-1');
  });
});

describe('строка списка называет родителя плашкой (UI-152)', () => {
  function badge(container: HTMLElement): HTMLElement {
    return container.querySelector('[data-mark="parents"]') as HTMLElement;
  }

  it('у задачи верхнего уровня в таблице без дочерних плашки и гнезда нет, ссылка одна', () => {
    const { container } = tableRow(task('DEMO-3', { parents: [] }));

    expect(caption(container)).toBeNull();
    expect(screen.getAllByRole('link')).toHaveLength(1);
    expect(container.querySelector('td span[class*="--ui-parent-slot"]')).toBeNull();
  });

  it('гнездо под плашку есть у всех строк таблицы с дочерней задачей — и у строки без родителя', () => {
    const { container } = tableRow(task('DEMO-3', { parents: [] }), true);

    // Название той же ширины, что у соседа с родителем: гнездо одно у всех строк.
    const slot = container.querySelector('td span[class*="--ui-parent-slot"]');
    expect(slot).not.toBeNull();
    expect(slot).toBeEmptyDOMElement();
    expect(caption(container)).toBeNull();
  });

  it('плашка стоит в гнезде после названия, говорит словом «родитель» и ключом, строка не растёт', () => {
    const { container } = tableRow(task('DEMO-5', { parents: [PROGRAM] }), true);

    const shown = badge(container);
    const cell = screen.getByRole('link', { name: 'Задача DEMO-5' }).closest('td');
    expect(cell).toContainElement(shown);
    // Название первым: его начало стоит на одном месте у всех строк.
    expect(cell?.querySelector('a')).toHaveAttribute('href', '/tasks/DEMO-5');
    expect(shown.parentElement?.className).toContain('w-(--ui-parent-slot)');

    // Кнопка, а не ссылка: нажатие раскрывает, а не уводит. Слово — не одна стрелка.
    expect(shown.tagName).toBe('BUTTON');
    expect(shown).toHaveTextContent(`${say.ui('task.parents.badge')}${PROGRAM.key}`);
    expect(within(shown).getByText(PROGRAM.key)).toHaveClass('font-mono');
    expect(shown).toHaveAttribute('aria-expanded', 'false');
    // На телефоне мишень не мельче 24 px (UI-154), как у значков признаков (UI-163).
    expect(shown).toHaveClass('max-fold:min-h-(--ui-tap)');
    // Ссылка в строке одна — своя; в родителя ведёт панель.
    expect(screen.getAllByRole('link')).toHaveLength(1);
    expect(container.querySelector('tr')).toHaveClass('h-(--ui-row-height)');
  });

  it('двух родителей не прячет: плашка «родители KEY +1»', () => {
    const { container } = tableRow(task('DEMO-5', { parents: [PROGRAM, SECOND] }), true);

    expect(badge(container)).toHaveTextContent(
      `${say.ui('task.parents.badgeMany')}${PROGRAM.key}${say.ui('task.parents.more', { count: 1 })}`,
    );
  });

  it('клик по остальной строке задачи с родителем ведёт в саму задачу', async () => {
    const user = userEvent.setup();
    tableRow(task('DEMO-5', { parents: [PROGRAM, SECOND] }), true);

    // Знак приоритета: ни ссылок, ни кнопок в ячейке нет, уводит обработчик строки.
    await user.click(screen.getByText('normal'));
    expect(where.current).toBe('/tasks/DEMO-5');
  });

  it('обводку строки зажигает только её собственная ссылка, а не плашка родителя', () => {
    const { container } = tableRow(task('DEMO-5', { parents: [PROGRAM] }), true);

    const own = screen.getByRole('link', { name: 'Задача DEMO-5' });
    expect(own).toHaveAttribute('data-link', 'task');
    expect(badge(container)).not.toHaveAttribute('data-link');
  });
});

describe('панель плашки говорит, чей это родитель (UI-152)', () => {
  const heading = (key: 'task.parents.heading' | 'task.parents.headingMany', of: string) =>
    say.ui(key, { key: of }).replace(/<\/?key>/g, '');

  it('называет задачу строки словами и ведёт в родителя ссылкой с полным названием', async () => {
    const user = userEvent.setup();
    const { container } = show(<ParentPanel parents={[PROGRAM]} childKey="DEMO-5" />);

    // «Родитель задачи DEMO-5»: сказано словами, в какую сторону связь.
    expect(container).toHaveTextContent(heading('task.parents.heading', 'DEMO-5'));
    const link = screen.getByRole('link');
    expect(link).toHaveTextContent(say.ui('task.parents.item', PROGRAM));
    // Название родителя переносится, а не режется: панель и есть путь к полному тексту.
    expect(link).not.toHaveClass('truncate');
    expect(link).toHaveClass('wrap-anywhere');

    await user.click(link);
    expect(where.current).toBe('/tasks/DEMO-2');
  });

  it('при двух родителях — «Родители задачи X» и оба ссылками в порядке связи', () => {
    const { container } = show(<ParentPanel parents={[PROGRAM, SECOND]} childKey="DEMO-5" />);

    expect(container).toHaveTextContent(heading('task.parents.headingMany', 'DEMO-5'));
    expect(screen.getAllByRole('link').map((node) => node.getAttribute('href'))).toEqual([
      '/tasks/DEMO-2',
      '/tasks/DEMO-8',
    ]);
  });
});
