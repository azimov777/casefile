import { http } from 'msw';
import userEvent from '@testing-library/user-event';
import { screen, within } from '@testing-library/react';
import { beforeEach, describe, expect, it } from 'vitest';
import { API, bootstrap, collection, data, failure } from '@testing/msw/responses';
import { server } from '@testing/msw/server';
import { renderApp } from '@testing/render';
import { say } from '@testing/say';
import { setToken } from '@/shared/api';

beforeEach(() => {
  // Список задач под шапкой ходит за своей страницей: без обработчика подмена
  // ругалась бы на неперехваченный запрос.
  server.use(http.get(`${API}/api/v1/tasks`, () => collection([])));
  setToken('trk_test');
});

/** Отказывает столько раз, сколько сказано, потом отвечает как обычно. */
function flakyBootstrap(failures: number) {
  let left = failures;
  return http.get(`${API}/api/v1/bootstrap`, () => {
    if (left > 0) {
      left -= 1;
      return failure('database_unavailable', 503, 'Database is not available');
    }
    return data(bootstrap());
  });
}

describe('боковая панель', () => {
  it('на отказе показывает текст по коду и наполняется по кнопке «Повторить»', async () => {
    server.use(flakyBootstrap(1));
    renderApp('/tasks');

    expect(await screen.findByRole('alert')).toHaveTextContent(say.errors('database_unavailable'));
    expect(screen.queryByText('owner')).not.toBeInTheDocument();

    await userEvent.setup().click(screen.getByRole('button', { name: say.ui('query.retry') }));

    // Повтор — это `refetch`, а не перезагрузка: страница рядом с панелью та же.
    expect(await screen.findByText('owner')).toBeInTheDocument();
    expect(screen.getByText(say.ui('app.openQuestions', { count: 2 }))).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: say.ui('query.retry') })).not.toBeInTheDocument();
    expect(screen.getByRole('heading', { name: say.tasks('title') })).toBeInTheDocument();
  });

  it('счётчик вопросов читается числом с подписью, а не голой цифрой', async () => {
    server.use(http.get(`${API}/api/v1/bootstrap`, () => data(bootstrap())));
    renderApp('/tasks');

    // Диктору «2» рядом со словом «Входящая» досталось бы частью названия раздела,
    // поэтому число подписано, а сама цифра от него скрыта.
    const inbox = await screen.findByRole('link', {
      name: `${say.ui('app.inbox')} ${say.ui('app.openQuestions', { count: 2 })}`,
    });
    expect(inbox).toHaveAttribute('href', '/questions');
  });

  it('при нуле вопросов счётчик называется иначе и не требует внимания', async () => {
    server.use(http.get(`${API}/api/v1/bootstrap`, () => data(bootstrap({ open_questions: 0 }))));
    renderApp('/tasks');

    const quiet = await screen.findByRole('link', {
      name: `${say.ui('app.inbox')} ${say.ui('app.openQuestions', { count: 0 })}`,
    });
    expect(quiet).toHaveAttribute('href', '/questions');

    // Вторая половина того же: ноль не требует внимания. Счётчик приглушён, а не
    // набран тоном тревоги, — и это проверяется цветом, а не подписью, потому что
    // подпись у нуля своя и о тоне ничего не говорит.
    const counter = within(quiet).getByText('0').parentElement;
    expect(counter).toHaveClass('text-faint');
    expect(counter).not.toHaveClass('text-attention');
  });

  it('очереди из bootstrap — места, и текущее помечено `aria-current`', async () => {
    server.use(http.get(`${API}/api/v1/bootstrap`, () => data(bootstrap())));
    renderApp('/tasks?queue=DEMO&view=board&status=open');

    const demo = await screen.findByRole('link', { name: /DEMO/ });
    expect(demo).toHaveAttribute('aria-current', 'page');
    // Переход в очередь сохраняет вид и остальной отбор: меняется только очередь.
    expect(demo).toHaveAttribute('href', '/tasks?view=board&queue=DEMO&status=open');

    const all = screen.getByRole('link', { name: say.ui('app.allTasks') });
    expect(all).not.toHaveAttribute('aria-current');
    expect(all).toHaveAttribute('href', '/tasks?view=board&status=open');
  });

  it('длинное название очереди видно целиком, переносом, а не только в подсказке', async () => {
    const title = 'Трекер: интерфейс человека, который ведут агенты, и его доводка';
    const base = bootstrap();
    server.use(
      http.get(`${API}/api/v1/bootstrap`, () =>
        data(bootstrap({ queues: [{ ...base.queues[0]!, key: 'UI', title }] })),
      ),
    );
    renderApp('/tasks');

    const link = await screen.findByRole('link', { name: new RegExp(title) });
    /*
     * Наведения на телефоне нет (UI-153): подсказка `title` не в счёт. Название стоит в
     * пункте текстом целиком и переносится, а многоточием не режется. Ширину jsdom не
     * считает, поэтому проверяется то, чем обрезка задаётся: классом `truncate`.
     */
    const shown = within(link).getByText(title);
    expect(shown).not.toHaveClass('truncate');
    expect(shown).toHaveClass('wrap-anywhere');
  });

  it('во входящей помечен раздел, а не очередь', async () => {
    server.use(http.get(`${API}/api/v1/bootstrap`, () => data(bootstrap())));
    server.use(http.get(`${API}/api/v1/questions`, () => collection([])));
    server.use(http.get(`${API}/api/v1/remarks`, () => collection([])));
    renderApp('/questions');

    expect(
      await screen.findByRole('link', { name: new RegExp(say.ui('app.inbox')) }),
    ).toHaveAttribute('aria-current', 'page');
    expect(screen.getByRole('link', { name: say.ui('app.allTasks') })).not.toHaveAttribute(
      'aria-current',
    );
  });

  it('длинное имя участника не расширяет панель, а переносится', async () => {
    server.use(
      http.get(`${API}/api/v1/bootstrap`, () =>
        data(
          bootstrap({
            participant: {
              ...bootstrap().participant!,
              name: 'очень-длинное-имя-участника-которое-никто-не-выбирал',
            },
          }),
        ),
      ),
    );
    renderApp('/tasks');

    // Имя участника — чужая строка: её длину интерфейс не выбирает, и перенос по любому
    // месту здесь единственный способ не получить горизонтальную прокрутку.
    const name = await screen.findByText('очень-длинное-имя-участника-которое-никто-не-выбирал');
    expect(name).toHaveClass(/break-all/);
  });

  it('действий, меняющих данные, в панели нет: единственная кнопка — выход', async () => {
    server.use(http.get(`${API}/api/v1/bootstrap`, () => data(bootstrap())));
    renderApp('/tasks');
    await screen.findByText('owner');

    const side = screen.getByRole('complementary', { name: say.ui('app.trackerSections') });
    const buttons = within(side)
      .getAllByRole('button')
      .map((button) => button.textContent);
    expect(buttons).toEqual([say.ui('app.signOut')]);
  });

  it('неизвестный код показывает фразу бэкенда и сам код', async () => {
    server.use(
      http.get(`${API}/api/v1/bootstrap`, () =>
        failure('brand_new_code', 500, 'Something odd happened'),
      ),
    );
    renderApp('/tasks');

    expect(await screen.findByRole('alert')).toHaveTextContent(
      say.ui('error.withCode', { message: 'Something odd happened', code: 'brand_new_code' }),
    );
  });
});
