import { MemoryRouter } from 'react-router';
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { entryOfType, summaryEntry } from '@testing/msw/responses';
import { say } from '@testing/say';
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
 *
 * Подписи берутся из словаря тем же ключом, что и в коде, а идентификаторы контракта
 * (`goal`, `blocked_by`, `DEMO-2`) стоят строками: они не переводятся. Собирается
 * словарь функцией, а не значением модуля, потому что подпись зависит от языка,
 * а он подставляется в тесте.
 */
function expected(): Record<EntryType, (string | RegExp)[]> {
  return {
    summary: [
      say.ui('entry.summary.done'),
      say.ui('entry.summary.remaining'),
      say.ui('entry.summary.blockers'),
      say.ui('entry.summary.nextStep'),
    ],
    decision: [/Тело записи/],
    attempt: [/Тело записи/],
    finding: [/Тело записи/],
    artifact: [/Тело записи/, say.ui('entry.refs')],
    note: [/Тело записи/],
    created: [say.ui('entry.headline.created')],
    question: [say.ui('entry.addressees'), 'owner', say.ui('entry.blocking')],
    answer: [say.ui('entry.headline.answerTo'), 'DEMO-1#1'],
    verdict: [say.ui('entry.headline.check', { no: 2 }), 'failed'],
    remark: [/Тело записи/],
    // Исход — словами: замечание оставил человек, и «accepted» ему ни о чём не говорит.
    resolution: [
      say.ui('entry.headline.resolution'),
      'DEMO-1#1',
      say.ui('entry.remarkOutcome.accepted'),
      'DEMO-2',
    ],
    status_changed: [
      say.ui('entry.headline.status'),
      'in_progress',
      'open',
      /Задан блокирующий вопрос/,
    ],
    section_changed: [
      say.ui('entry.headline.sectionEdited'),
      'goal',
      say.ui('entry.was'),
      say.ui('entry.now'),
      'Старая цель',
      'Новая цель',
    ],
    field_changed: [
      say.ui('entry.headline.fieldEdited'),
      'priority',
      say.ui('entry.was'),
      say.ui('entry.now'),
      'normal',
      'critical',
    ],
    assignee_changed: [
      say.ui('entry.headline.assignee'),
      say.ui('entry.headline.none'),
      'demo_agent',
    ],
    link_added: [say.ui('entry.headline.linkAdded'), 'blocked_by', 'DEMO-2'],
    link_removed: [say.ui('entry.headline.linkRemoved'), 'blocked_by', 'DEMO-2'],
    attribute_created: [say.ui('entry.headline.attributeCreated'), 'repo', 'github.com/demo'],
    attribute_changed: [
      say.ui('entry.headline.attributeChanged'),
      'repo',
      say.ui('entry.was'),
      say.ui('entry.now'),
      'github.com/old',
      'github.com/demo',
      /Репозиторий переехал/,
    ],
    attribute_removed: [
      say.ui('entry.headline.attributeRemoved'),
      'repo',
      'github.com/demo',
      /Репозиторий закрыт/,
    ],
  };
}

/**
 * Типы, чей заголовок собирает трекер по фактам: показывать вместо него присланный
 * `title` нельзя ни на каком языке.
 */
const BUILT_HEADLINE: EntryType[] = [
  'created',
  'answer',
  'verdict',
  'resolution',
  'status_changed',
  'section_changed',
  'field_changed',
  'assignee_changed',
  'link_added',
  'link_removed',
  'attribute_created',
  'attribute_changed',
  'attribute_removed',
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
    for (const wanted of expected()[type]) {
      if (typeof wanted === 'string') expect(shown).toContain(wanted);
      else expect(shown).toMatch(wanted);
    }

    // Сырая нагрузка на экране выглядела бы как JSON: фигурные скобки с кавычками.
    expect(container.textContent).not.toMatch(/\{"|":\s*"/);

    /*
     * Заголовок, приехавший в записи готовой строкой, вместо собранного по фактам
     * не показывается. Проверка сравнивает с самой этой строкой, а не со списком
     * английских заготовок трекера: на английском интерфейсе «Status changed» —
     * законная подпись из словаря, и список перестал бы что-либо различать.
     */
    if (BUILT_HEADLINE.includes(type)) {
      expect(shown).not.toContain(entryOfType(5, 'DEMO-1', type).title);
    }
  });

  it('у сводки заголовок не повторяет «следующий шаг» из её же тела', () => {
    const { container } = show('summary');

    const step = screen.getByText(say.ui('entry.summary.nextStep')).closest('div');
    const value = step?.textContent ?? '';
    expect(value).not.toBe('');
    // Заголовок сводки выводится трекером из первой строки «следующего шага»: показать
    // его вторым разом жирным над тем же текстом значит занять две строки ничем.
    expect(container.querySelectorAll('h3')).toHaveLength(0);
  });

  it('пятая часть сводки: с `unmeasured` рисует подпись и текст (TRK-78, UI-120)', () => {
    const entry = summaryEntry(5, 'DEMO-1');
    const withUnmeasured = {
      ...entry,
      payload: {
        ...entry.payload,
        unmeasured: 'Прод-путь не проверялся: гонял только дев-контур',
      },
    };

    render(
      <MemoryRouter>
        <EntryCard entry={withUnmeasured} checks={[]} />
      </MemoryRouter>,
    );

    expect(screen.getByText(say.ui('entry.summary.unmeasured'))).toBeInTheDocument();
    expect(
      screen.getByText('Прод-путь не проверялся: гонял только дев-контур'),
    ).toBeInTheDocument();
  });

  it('пятая часть сводки: без `unmeasured` не рисует ни подписи, ни пустого блока', () => {
    // `summaryEntry` не кладёт `unmeasured` в нагрузку вовсе — тот же случай, что у
    // промежуточных сводок и у всех дел, закрытых до TRK-78.
    const { container } = render(
      <MemoryRouter>
        <EntryCard entry={summaryEntry(5, 'DEMO-1')} checks={[]} />
      </MemoryRouter>,
    );

    expect(screen.queryByText(say.ui('entry.summary.unmeasured'))).not.toBeInTheDocument();
    // Четыре части — по числу `<dt>` в разметке: пятая не рисует пустой заголовок.
    expect(container.querySelectorAll('dt')).toHaveLength(4);
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
    expect(was).toHaveTextContent(say.ui('entry.was'));
    expect(now).toHaveTextContent(say.ui('entry.now'));
    expect(container.textContent?.indexOf(say.ui('entry.was'))).toBeLessThan(
      container.textContent?.indexOf(say.ui('entry.now')) ?? -1,
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

  /*
   * jsdom не считает реальную геометрию строки — за неё отвечает сквозной тест
   * (`e2e/reason-line.spec.ts`, UI-159). Здесь только застёжка от возврата причины
   * в `BLOCK` (`flex flex-col`, `entry-body.tsx`): под ним текстовые узлы вокруг
   * ссылки (до неё, сама ссылка, после неё) становятся отдельными флекс-элементами
   * и встают друг под другом — «(», ссылка и «)» тремя строками, как было в UI-159.
   * Обычный абзац оставляет их одним строчным потоком.
   */
  it('причина со ссылкой `KEY#N` не завёрнута в блочную колонку (UI-159)', () => {
    const entry = entryOfType(8, 'DEMO-1', 'status_changed');
    const withRef = {
      ...entry,
      payload: { ...entry.payload, reason: 'Заблокировано (DEMO-1#1) до ответа владельца' },
    } as typeof entry;

    const { container } = render(
      <MemoryRouter>
        <EntryCard entry={withRef} checks={[]} />
      </MemoryRouter>,
    );

    const paragraph = container.querySelector('[data-type="status_changed"] p');
    expect(paragraph).not.toBeNull();
    expect(paragraph?.className.split(' ')).not.toEqual(expect.arrayContaining(['flex']));
    expect(screen.getByRole('link', { name: 'DEMO-1#1' })).toBeVisible();
  });
});
