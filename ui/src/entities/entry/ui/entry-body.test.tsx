import { MemoryRouter } from 'react-router';
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { entryOfType } from '@testing/msw/responses';
import { ENTRY_TYPES, type EntryType } from '../api/entries';
import { EntryCard } from './entry-card';

/**
 * Что должно быть видно в записи каждого типа — в карточке целиком, а не только в теле:
 * часть содержания служебной записи живёт в её заголовке, и делить проверку между
 * заголовком и телом значило бы проверять вёрстку, а не то, что человек прочитает.
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
  created: ['Задача заведена'],
  question: ['Кому:', 'owner', 'блокирующий'],
  answer: ['Ответ на', 'DEMO-1#1'],
  verdict: ['Обзорная проверка 2', 'failed'],
  remark: [/Тело записи/],
  // Исход — словами: замечание оставил человек, и «accepted» ему ни о чём не говорит.
  resolution: ['Разбор', 'DEMO-1#1', 'принято в работу', 'DEMO-2'],
  status_changed: ['Статус', 'in_progress', 'open', /Задан блокирующий вопрос/],
  section_changed: ['Правка раздела', 'goal', 'Было', 'Стало', 'Старая цель', 'Новая цель'],
  field_changed: ['Правка поля', 'priority', 'Было', 'Стало', 'normal', 'critical'],
  assignee_changed: ['Исполнитель', 'не назначен', 'demo_agent'],
  link_added: ['Связь', 'blocked_by', 'DEMO-2'],
  link_removed: ['Связь снята', 'blocked_by', 'DEMO-2'],
};

/** Английские заготовки трекера: в русском интерфейсе их быть не должно ни у одного типа. */
const ENGLISH = [
  'Task created',
  'Resolution of',
  'Status changed',
  'Section changed',
  'Field changed',
  'Assignee changed',
  'Link added',
  'Link removed',
  'Answer to',
  'Verdict on',
];

function show(type: EntryType) {
  const entry = entryOfType(type === 'answer' ? 2 : 5, 'DEMO-1', type);
  return render(
    <MemoryRouter>
      <EntryCard entry={entry} checks={['Первая проверка', 'Вторая проверка']} />
    </MemoryRouter>,
  );
}

describe('представление записи по типу', () => {
  it.each(ENTRY_TYPES)('%s показан своим представлением, а не сырой нагрузкой', (type) => {
    const { container } = show(type);

    // Проверяется текст карточки целиком, а не отдельный узел: одно и то же слово
    // законно встречается дважды — `demo_agent` стоит и в авторе записи, и в её
    // заголовке, — и строгий поиск по узлу падал бы на этом, ничего не проверив.
    const shown = container.textContent ?? '';
    for (const expected of EXPECTED[type]) {
      if (typeof expected === 'string') expect(shown).toContain(expected);
      else expect(shown).toMatch(expected);
    }

    // Сырая нагрузка на экране выглядела бы как JSON: фигурные скобки с кавычками.
    expect(container.textContent).not.toMatch(/\{"|":\s*"/);

    // Заголовок, собранный трекером по-английски, в русский интерфейс не попадает.
    for (const english of ENGLISH) {
      expect(container.textContent).not.toContain(english);
    }
  });

  it('у сводки заголовок не повторяет «следующий шаг» из её же тела', () => {
    const { container } = show('summary');

    const step = screen.getByText('Следующий шаг').closest('div');
    const value = step?.textContent ?? '';
    expect(value).not.toBe('');
    // Заголовок сводки выводится трекером из первой строки «следующего шага»: показать
    // его вторым разом жирным над тем же текстом значит занять две строки ничем.
    expect(container.querySelectorAll('h3')).toHaveLength(0);
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

describe('сравнение раздела', () => {
  it('стороны различаются тоном и подписью, а порядок чтения остаётся прежним', () => {
    const { container } = show('section_changed');

    const sides = Array.from(container.querySelectorAll('[data-side]'));
    expect(sides).toHaveLength(2);

    // Тон исхода: у «было» и «стало» разные классы, то есть разные цвета (решение Д14).
    const [was, now] = sides as [HTMLElement, HTMLElement];
    expect(was.className).not.toBe(now.className);

    // Цвет при этом не единственный носитель: подписи на месте и идут в том порядке,
    // в котором их прочитает программа чтения с экрана.
    expect(was).toHaveTextContent('Было');
    expect(now).toHaveTextContent('Стало');
    expect(container.textContent?.indexOf('Было')).toBeLessThan(
      container.textContent?.indexOf('Стало') ?? -1,
    );
  });
});

describe('служебная запись', () => {
  it('без причины умещается в строку шапки, с причиной показывает её целиком', () => {
    const entry = entryOfType(5, 'DEMO-1', 'status_changed');

    // С причиной: свободный текст показан целиком — это то, чего в заголовке быть
    // не может, и ради него у служебной записи вообще есть тело.
    const withReason = render(
      <MemoryRouter>
        <EntryCard entry={entry} checks={[]} />
      </MemoryRouter>,
    );
    expect(withReason.container).toHaveTextContent('Задан блокирующий вопрос');
    withReason.unmount();

    // Без причины: тела нет вовсе, весь факт уместился в шапку. Заголовок и тело
    // не должны говорить одно и то же (`docs/notes/ui.md`).
    const bare = render(
      <MemoryRouter>
        <EntryCard
          entry={{ ...entry, payload: { ...entry.payload, reason: null } } as typeof entry}
          checks={[]}
        />
      </MemoryRouter>,
    );
    const card = bare.container.querySelector('[data-type="status_changed"]');
    expect(card).not.toBeNull();
    expect(card?.querySelectorAll('p')).toHaveLength(0);
    expect(card).toHaveTextContent(/backlog|open|in_progress/);
  });
});
