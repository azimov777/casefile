import { MemoryRouter } from 'react-router';
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { entryOfType } from '@testing/msw/responses';
import { ENTRY_TYPES, type EntryType } from '../api/entries';
import { EntryBody } from './entry-body';

/**
 * Что должно быть видно в записи каждого типа.
 *
 * Словарь полный (`Record<EntryType, ...>`): тип, добавленный в контракт, уронит
 * сборку теста — и это единственный способ не выпустить в ленту запись, показанную
 * сырой нагрузкой.
 */
const EXPECTED: Record<EntryType, (string | RegExp)[]> = {
  summary: ['Сделано', 'Осталось', 'Что мешает', 'Следующий шаг'],
  decision: [/Тело записи/],
  attempt: [/Тело записи/],
  finding: [/Тело записи/],
  artifact: [/Тело записи/, 'Указатели:'],
  note: [/Тело записи/],
  created: [/Тело записи/],
  question: ['Кому:', 'owner', 'блокирующий'],
  answer: ['Ответ на', 'DEMO-1#1'],
  verdict: ['Проверка 2', 'failed'],
  status_changed: ['in_progress', 'open', /Задан блокирующий вопрос/],
  section_changed: ['goal', 'Было', 'Стало', 'Старая цель', 'Новая цель'],
  field_changed: ['priority', 'Было', 'Стало', 'normal', 'critical'],
  assignee_changed: ['не назначена', 'demo_agent'],
  link_added: ['blocked_by', 'DEMO-2'],
  link_removed: ['blocked_by', 'DEMO-2'],
};

function show(type: EntryType) {
  const entry = entryOfType(type === 'answer' ? 2 : 5, 'DEMO-1', type);
  return render(
    <MemoryRouter>
      <EntryBody entry={entry} checks={['Первая проверка', 'Вторая проверка']} />
    </MemoryRouter>,
  );
}

describe('представление записи по типу', () => {
  it.each(ENTRY_TYPES)('%s показан своим представлением, а не сырой нагрузкой', (type) => {
    const { container } = show(type);

    for (const expected of EXPECTED[type]) {
      expect(screen.getByText(expected, { exact: false })).toBeInTheDocument();
    }

    // Сырая нагрузка на экране выглядела бы как JSON: фигурные скобки с кавычками.
    expect(container.textContent).not.toMatch(/\{"|":\s*"/);
  });

  it('вердикт называет проверку её текстом из задачи, а не только номером', () => {
    show('verdict');

    expect(screen.getByText('Вторая проверка')).toBeInTheDocument();
  });

  it('в указателях адрес становится ссылкой, а ключ задачи — переходом в приложение', () => {
    show('artifact');

    expect(screen.getByRole('link', { name: 'https://example.test/build/42' })).toHaveAttribute(
      'href',
      'https://example.test/build/42',
    );
    expect(screen.getAllByRole('link', { name: 'DEMO-2' })[0]).toHaveAttribute(
      'href',
      '/tasks/DEMO-2',
    );
  });
});
