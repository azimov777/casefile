import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { say } from '@testing/say';
import { TASK_PRIORITIES, TASK_STATUSES } from '../api/tasks';
import { LINK_KIND_ORDER, LinkKindMark } from './link-kind';
import { PriorityMark } from './priority-mark';
import { StatusMark } from './status-mark';

/** Рисунок знака: разметка `svg` без обёрток — по ней и сравниваются формы. */
function shapeOf(container: HTMLElement): string {
  const svg = container.querySelector('svg');
  if (svg === null) throw new Error('У знака нет рисунка');
  return svg.innerHTML;
}

describe('знак статуса', () => {
  it('у каждого статуса контракта своя форма, и две формы не совпадают', () => {
    // Список берётся из контракта, а не переписывается здесь: статус, добавленный
    // в контракт, обязан уронить сборку `satisfies Record<TaskStatus, ...>`,
    // а не остаться без формы молча.
    const shapes = TASK_STATUSES.map((status) => {
      const { container, unmount } = render(<StatusMark status={status} />);
      const shape = shapeOf(container);
      unmount();
      return shape;
    });

    expect(new Set(shapes).size).toBe(TASK_STATUSES.length);
  });

  it('доступное имя называет род и значение', () => {
    render(<StatusMark status="in_progress" />);

    expect(screen.getByText('in_progress').parentElement).toHaveTextContent(
      `${say.ui('task.statusLabel')} in_progress`,
    );
  });

  it('без подписи значение не пропадает, а уходит в доступное имя', () => {
    const { container } = render(<StatusMark status="done" withName={false} />);

    expect(container).toHaveTextContent(`${say.ui('task.statusLabel')} done`);
    expect(container.querySelector('.sr-only')).not.toBeNull();
  });

  it('значение вне контракта не роняет отрисовку и показывается нейтральной формой', () => {
    const { container } = render(<StatusMark status="выдуманный" />);

    expect(shapeOf(container)).toBeTruthy();
    expect(container).toHaveTextContent('выдуманный');
  });

  it('пустого значения не бывает: знака тогда нет вовсе', () => {
    const { container } = render(<StatusMark status={null} />);

    expect(container).toBeEmptyDOMElement();
  });
});

describe('знак приоритета', () => {
  it('у каждого приоритета контракта своя форма, и две формы не совпадают', () => {
    const shapes = TASK_PRIORITIES.map((priority) => {
      const { container, unmount } = render(<PriorityMark priority={priority} />);
      const shape = shapeOf(container);
      unmount();
      return shape;
    });

    expect(new Set(shapes).size).toBe(TASK_PRIORITIES.length);
  });

  it('доступное имя называет род и значение', () => {
    render(<PriorityMark priority="critical" />);

    expect(screen.getByText('critical').parentElement).toHaveTextContent(
      `${say.ui('task.priorityLabel')} critical`,
    );
  });

  it('форма статуса и форма приоритета не совпадают ни в одной паре', () => {
    const statuses = TASK_STATUSES.map((status) => {
      const { container, unmount } = render(<StatusMark status={status} />);
      const shape = shapeOf(container);
      unmount();
      return shape;
    });
    const priorities = TASK_PRIORITIES.map((priority) => {
      const { container, unmount } = render(<PriorityMark priority={priority} />);
      const shape = shapeOf(container);
      unmount();
      return shape;
    });

    // Ради этого задача и заведена: рядом стоящие колонки различаются до чтения слова.
    expect(statuses.filter((shape) => priorities.includes(shape))).toEqual([]);
  });
});

describe('знак вида связи (UI-125)', () => {
  it('у каждого вида контракта своя форма, и две формы не совпадают', () => {
    // Список берётся из порядка групп, а не переписывается здесь: вид, добавленный
    // в контракт и забытый в `LINK_KIND_ORDER`, роняет сборку сам, а не тихо
    // остаётся без знака.
    const shapes = LINK_KIND_ORDER.map((kind) => {
      const { container, unmount } = render(<LinkKindMark kind={kind} />);
      const shape = shapeOf(container);
      unmount();
      return shape;
    });

    expect(new Set(shapes).size).toBe(LINK_KIND_ORDER.length);
  });

  it('идентификатор контракта стоит моноширинным и не обрезается', () => {
    render(<LinkKindMark kind="blocked_by" />);

    // Сам идентификатор — текст без сокращения, ровно как в контракте.
    expect(screen.getByText('blocked_by')).toHaveClass('font-mono');
  });

  it('подпись на языке человека стоит рядом с идентификатором, а не вместо него', () => {
    render(<LinkKindMark kind="blocked_by" />);

    expect(screen.getByText('blocked_by')).toBeInTheDocument();
    expect(screen.getByText(say.ui('task.links.kind.blocked_by'))).toBeInTheDocument();
  });

  it('у каждого вида своя подпись: перепутать группы нельзя даже на слух', () => {
    const captions = LINK_KIND_ORDER.map((kind) => say.ui(`task.links.kind.${kind}`));

    expect(new Set(captions).size).toBe(LINK_KIND_ORDER.length);
  });
});
