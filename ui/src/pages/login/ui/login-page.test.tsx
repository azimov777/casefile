import { HttpResponse, http } from 'msw';
import userEvent from '@testing-library/user-event';
import { screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it } from 'vitest';
import { API, bootstrap, collection, data, failure } from '@testing/msw/responses';
import { server } from '@testing/msw/server';
import { renderApp } from '@testing/render';
import { say } from '@testing/say';
import { setToken } from '@/shared/api';
import { en, ru } from '@/shared/i18n';

const VALID = 'trk_valid';

/** Токен проверяется настоящим запросом, поэтому подмена смотрит на заголовок. */
function bootstrapByToken(payload = bootstrap()) {
  return http.get(`${API}/api/v1/bootstrap`, ({ request }) => {
    if (request.headers.get('Authorization') !== `Bearer ${VALID}`) {
      return failure('unauthorized', 401, 'Authentication required');
    }
    return data(payload);
  });
}

// Удачный вход уводит на список задач, и тот сразу идёт за своей страницей.
// Без этого обработчика подмена ругалась бы на неперехваченный запрос, а экран,
// на котором проверяют шапку, стоял бы в отказе.
beforeEach(() => {
  server.use(http.get(`${API}/api/v1/tasks`, () => collection([])));
});

/*
 * Подписи берутся из словаря тем же ключом, что и в коде, а не повторены строкой:
 * правка формулировки не роняет десяток тестов, а пропавший ключ роняет. Язык
 * `say` берёт у экземпляра в момент вызова, поэтому та же строка работает и в тесте
 * по умолчанию (английском), и в русском.
 */
async function submitToken(token: string) {
  const user = userEvent.setup();
  await user.type(screen.getByLabelText(say.login('tokenLabel')), token);
  await user.click(screen.getByRole('button', { name: say.login('submit') }));
}

/*
 * Язык здесь не подставляется: проверяется поведение входа, а не язык, и умолчание
 * страничного теста — язык приложения. Подписи при этом всё равно берутся из словаря
 * (`say`), а не повторены строкой: тому, что проверяет поведение, всё равно, на каком
 * языке подписана кнопка, но не всё равно, существует ли её ключ.
 */
describe('экран входа', () => {
  /**
   * Токены, из которых браузер не соберёт заголовок. Собираются кодами символов,
   * а не буквами: управляющий символ иначе не написать в исходнике, а кириллицу
   * в строке легко принять за латиницу, набранную по ошибке.
   */
  const CYRILLIC = `trk_${String.fromCharCode(1087, 1088, 1080)}`;
  const CONTROL = `trk_a${String.fromCharCode(1)}b`;

  it('токен с кириллицей объясняется видом токена, а не недоступным сервером', async () => {
    let asked = 0;
    server.use(
      http.get(`${API}/api/v1/bootstrap`, () => {
        asked += 1;
        return data(bootstrap());
      }),
    );
    renderApp('/login');

    await submitToken(CYRILLIC);

    expect(await screen.findByRole('alert')).toHaveTextContent(say.errors('token_not_header_safe'));
    expect(screen.queryByText(say.errors('network_error'))).not.toBeInTheDocument();
    // Запроса не было вовсе: заголовка из такого значения не выходит.
    expect(asked).toBe(0);
    expect(window.localStorage.getItem('tracker.token')).toBeNull();
  });

  it('токен с управляющим символом объясняется так же', async () => {
    server.use(bootstrapByToken());
    renderApp('/login');

    await submitToken(CONTROL);

    expect(await screen.findByRole('alert')).toHaveTextContent(say.errors('token_not_header_safe'));
  });

  it('токен без префикса trk_ уходит на сервер: формат интерфейс не угадывает', async () => {
    let seen: string | null = null;
    server.use(
      http.get(`${API}/api/v1/bootstrap`, ({ request }) => {
        seen = request.headers.get('Authorization');
        return failure('unauthorized', 401, 'Authentication required');
      }),
    );
    renderApp('/login');

    // Значение из годных для заголовка символов, но не похожее на токен: годен ли он
    // по существу, решает сервер, а не мы.
    await submitToken('not-a-tracker-token');

    expect(await screen.findByRole('alert')).toHaveTextContent(say.errors('unauthorized'));
    expect(seen).toBe('Bearer not-a-tracker-token');
  });

  it('при упавшей сети сообщение про недоступный сервер осталось', async () => {
    server.use(http.get(`${API}/api/v1/bootstrap`, () => HttpResponse.error()));
    renderApp('/login');

    await submitToken(VALID);

    expect(await screen.findByRole('alert')).toHaveTextContent(say.errors('network_error'));
  });

  it('испорченный токен в хранилище уводит на вход, а не на отказ сети', async () => {
    // Человек открывает список напрямую, а в хранилище лежит испорченное значение:
    // экрана входа на этом пути нет, и ошибиться причиной особенно легко.
    // Через `setToken`, а не мимо него: модуль держит значение и в памяти, и запись
    // прямо в хранилище прошла бы мимо этого снимка.
    setToken(CYRILLIC);
    server.use(http.get(`${API}/api/v1/bootstrap`, () => data(bootstrap())));

    renderApp('/tasks');

    expect(await screen.findByLabelText(say.login('tokenLabel'))).toBeInTheDocument();
    expect(window.localStorage.getItem('tracker.token')).toBeNull();
  });

  it('пускает с верным токеном и показывает участника и счётчик вопросов', async () => {
    server.use(bootstrapByToken());
    renderApp('/login');

    await submitToken(VALID);

    expect(await screen.findByText('owner')).toBeInTheDocument();
    expect(screen.getByText(say.ui('app.openQuestions', { count: 2 }))).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: say.tasks('title') })).toBeInTheDocument();
    expect(window.localStorage.getItem('tracker.token')).toBe(VALID);
  });

  it('на неверный токен показывает текст по коду и не сохраняет его', async () => {
    server.use(bootstrapByToken());
    renderApp('/login');

    await submitToken('trk_wrong');

    expect(await screen.findByRole('alert')).toHaveTextContent(say.errors('unauthorized'));
    expect(window.localStorage.getItem('tracker.token')).toBeNull();
    expect(screen.getByLabelText(say.login('tokenLabel'))).toBeInTheDocument();
  });

  it('не пускает общий агентский токен: за ним нет участника', async () => {
    server.use(bootstrapByToken(bootstrap({ participant: null, open_questions: 0 })));
    renderApp('/login');

    await submitToken(VALID);

    expect(await screen.findByRole('alert')).toHaveTextContent(say.errors('participant_required'));
    expect(window.localStorage.getItem('tracker.token')).toBeNull();
  });

  it('сообщает, что сервер недоступен, а не молчит', async () => {
    server.use(http.get(`${API}/api/v1/bootstrap`, () => Response.error()));
    renderApp('/login');

    await submitToken(VALID);

    expect(await screen.findByRole('alert')).toHaveTextContent(say.errors('network_error'));
  });

  it('пустое поле не отправляется', () => {
    renderApp('/login');
    expect(screen.getByRole('button', { name: say.login('submit') })).toBeDisabled();
  });

  it('вошедшего на экран входа не пускает', async () => {
    server.use(bootstrapByToken());
    renderApp('/login');

    await submitToken(VALID);
    await waitFor(() =>
      expect(screen.queryByLabelText(say.login('tokenLabel'))).not.toBeInTheDocument(),
    );
  });
});

describe('экран входа на английском', () => {
  it('заголовок, подпись поля, подсказка и кнопка — из английского словаря', () => {
    renderApp('/login');

    expect(screen.getByRole('heading', { name: en.login.title })).toBeInTheDocument();
    expect(screen.getByText(en.login.intro)).toBeInTheDocument();
    expect(screen.getByLabelText(en.login.tokenLabel)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: en.login.submit })).toBeInTheDocument();
    // Подсказка собрана `<Trans>`: команда внутри фразы стоит отдельным элементом,
    // а не двумя ключами по краям.
    expect(screen.getByText('docker compose run --rm init').tagName).toBe('CODE');
  });

  it('русской подписи на английском экране не осталось ни одной', () => {
    const { container } = renderApp('/login');

    /*
     * Единственная законная кириллица экрана — название языка `Русский` в списке
     * переключателя, а список Radix в jsdom не открывается: закрытый переключатель
     * показывает только выбранный язык. Значит на английском экране кириллицы нет
     * вовсе, и любое её появление — подпись, набранная мимо словаря.
     */
    const cyrillic = (container.textContent ?? '').match(/[А-Яа-яЁё]+/g) ?? [];
    expect([...new Set(cyrillic)]).toEqual([]);
  });

  it('отказ при неверном токене тоже английский', async () => {
    server.use(bootstrapByToken());
    renderApp('/login');

    const user = userEvent.setup();
    await user.type(screen.getByLabelText(en.login.tokenLabel), 'trk_wrong');
    await user.click(screen.getByRole('button', { name: en.login.submit }));

    expect(await screen.findByRole('alert')).toHaveTextContent(en.errors.unauthorized);
  });

  it('русский подставляется явно и берётся из своего словаря', () => {
    // Обратная сторона той же проверки: английский стал умолчанием, но русский
    // никуда не делся — те же места подписаны русским словарём.
    renderApp('/login', { language: 'ru' });

    expect(screen.getByRole('heading', { name: ru.login.title })).toBeInTheDocument();
    expect(screen.getByLabelText(ru.login.tokenLabel)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: ru.login.submit })).toBeInTheDocument();
  });

  it('переключатель языка стоит на самом входе: он нужен до входа, а не после', () => {
    renderApp('/login');

    // Открыть список Radix в jsdom нельзя — выбор проверяет сквозной сценарий; здесь
    // проверяется, что переключатель на экране есть и знает текущий язык.
    const trigger = screen.getByRole('combobox', { name: en.ui.language });
    expect(trigger).toHaveTextContent('English');
  });
});
