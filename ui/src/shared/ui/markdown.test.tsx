import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { describe, expect, it } from 'vitest';
import { Markdown } from './markdown';

const TABLE = [
  '| Сила | Словами людей / факт | Источник |',
  '| --- | --- | --- |',
  '| Push | "the context loss between sessions is brutal"; "essentially resetting its hour of work" | TRK-526#6 |',
].join('\n');

const DISCUSSION_REFS =
  'Ответ владельца TRK~16#4: заводить все кандидаты. Обсуждение TRK~16 закрыто итогом #5. А ~~это~~ зачёркнуто нарочно.';

describe('адреса обсуждений в одном абзаце', () => {
  /*
   * `remark-gfm` по умолчанию читает пару одиночных `~` как зачёркивание и съедает
   * тильды адресов `TRK~16#4` и `TRK~16`; зачёркивание остаётся только двойным `~~`.
   */
  it('не зачёркивают текст между собой, оба становятся ссылками, `~~` зачёркивает', () => {
    const { container } = render(
      <MemoryRouter>
        <Markdown>{DISCUSSION_REFS}</Markdown>
      </MemoryRouter>,
    );

    const dels = container.querySelectorAll('del');
    expect(dels).toHaveLength(1);
    expect(dels[0]).toHaveTextContent(/^это$/);
    expect(screen.getByRole('link', { name: 'TRK~16#4' })).toHaveAttribute(
      'href',
      '/discussions/TRK~16?entry=4',
    );
    expect(screen.getByRole('link', { name: 'TRK~16' })).toHaveAttribute(
      'href',
      '/discussions/TRK~16',
    );
  });
});

describe('таблица в разметке', () => {
  /*
   * Раскладку jsdom не считает: ширину столбца видит только браузер (живая проверка
   * в деле TRK-532). Здесь закреплены классы, из которых она складывается.
   */
  it('ячейки переносятся по словам, а не по буквам, и таблица прокручивается в своей обёртке', () => {
    render(
      <MemoryRouter>
        <Markdown>{TABLE}</Markdown>
      </MemoryRouter>,
    );

    const head = screen.getByRole('columnheader', { name: 'Сила' });
    const cell = screen.getByRole('cell', { name: 'Push' });
    // `wrap-break-word` перекрывает унаследованный `wrap-anywhere`: с ним `min-content`
    // ячейки — самое длинное слово, а не одна буква.
    expect(head).toHaveClass('wrap-break-word');
    expect(cell).toHaveClass('wrap-break-word');

    const scroller = screen.getByRole('table').parentElement;
    expect(scroller).toHaveClass('overflow-x-auto');
  });
});
