import { http } from 'msw';
import userEvent from '@testing-library/user-event';
import { screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it } from 'vitest';
import { API, bootstrap, collection, data, entryOfType, failure } from '@testing/msw/responses';
import { server } from '@testing/msw/server';
import { address, renderApp } from '@testing/render';
import { say } from '@testing/say';
import { setToken, type components } from '@/shared/api';

/*
 * Действия человека с проектом (UI-175): что видно какому набору ключа, что уходит
 * на бэкенд и чего не уходит, как читаются отказы на обоих языках.
 */

type Entry = components['schemas']['EntryRead'];
type ProjectDetail = components['schemas']['ProjectDetailRead'];

const STAMPS = { created_at: '2026-09-01T10:00:00Z', updated_at: '2026-09-02T10:00:00Z' };
const TOKEN_ID = '33333333-3333-3333-3333-333333333333';

function projectDetail(overrides: Partial<ProjectDetail> = {}): ProjectDetail {
  return {
    id: '22222222-2222-2222-2222-222222222222',
    key: 'DEMO',
    title: 'Демонстрация',
    description: 'Учебный проект.',
    last_task_number: 7,
    created_by: { kind: 'tracker', signature: null },
    ...STAMPS,
    attributes: [{ name: 'repo', value: 'github.com/demo', ...STAMPS }],
    ...overrides,
  };
}

/** Запись дела проекта с номером `no`: ответ на запись заметки или снятие. */
function projectEntry(no: number, type: Entry['type']): Entry {
  return { ...entryOfType(no, 'DEMO', type), task_key: null, project_key: 'DEMO' } as Entry;
}

/** Запросы записи прогона: метод, путь и тело — по ним видно, что ушло и чего не ушло. */
let writes: { method: string; path: string; body: unknown }[] = [];

function scope(value: 'task' | 'main') {
  server.use(
    http.get(`${API}/api/v1/bootstrap`, () =>
      data(bootstrap({ token: { id: TOKEN_ID, scope: value } })),
    ),
  );
}

async function remember(request: Request): Promise<void> {
  writes.push({
    method: request.method,
    path: new URL(request.url).pathname,
    body: await request.clone().json(),
  });
}

beforeEach(() => {
  writes = [];
  setToken('trk_test');
  server.use(
    http.get(`${API}/api/v1/tasks`, () => collection([])),
    http.get(`${API}/api/v1/projects/DEMO`, () => data(projectDetail())),
    http.get(`${API}/api/v1/projects/DEMO/entries`, () => collection([])),
    http.put(`${API}/api/v1/projects/DEMO/attributes/:name`, async ({ request, params }) => {
      await remember(request);
      const body = (await request.json()) as { value: string };
      return data({ name: String(params.name), value: body.value, ...STAMPS });
    }),
    http.post(`${API}/api/v1/projects/DEMO/attributes/:name/remove`, async ({ request }) => {
      await remember(request);
      return data(projectEntry(9, 'attribute_removed'));
    }),
    http.post(`${API}/api/v1/projects/DEMO/entries`, async ({ request }) => {
      await remember(request);
      return data(projectEntry(12, 'note'), 201);
    }),
    http.patch(`${API}/api/v1/projects/DEMO`, async ({ request }) => {
      await remember(request);
      return data(projectDetail());
    }),
    http.post(`${API}/api/v1/projects`, async ({ request }) => {
      await remember(request);
      return data({ ...projectDetail({ key: 'NEW', title: 'Новый' }), attributes: undefined }, 201);
    }),
  );
});

describe('видимость действий по набору ключа', () => {
  it('набор `task`: создания и правки карточки нет, атрибуты и заметки есть', async () => {
    scope('task');
    renderApp('/projects/DEMO', { language: 'ru' });

    const attributes = await screen.findByRole('region', { name: say.project('attributes') });
    expect(
      await within(attributes).findByRole('button', { name: say.project('attribute.add') }),
    ).toBeInTheDocument();
    expect(
      within(attributes).getByRole('button', {
        name: say.project('attribute.changeLabel', { name: 'repo' }),
      }),
    ).toBeInTheDocument();
    expect(
      within(attributes).getByRole('button', {
        name: say.project('attribute.removeLabel', { name: 'repo' }),
      }),
    ).toBeInTheDocument();
    expect(screen.getByRole('button', { name: say.project('note.open') })).toBeInTheDocument();

    expect(screen.queryByRole('button', { name: say.project('edit.open') })).toBeNull();
    expect(screen.queryByRole('button', { name: say.project('create.open') })).toBeNull();
  });

  it('набор `main`: сверх того правка карточки и «Новый проект» в панели', async () => {
    scope('main');
    renderApp('/projects/DEMO', { language: 'ru' });

    expect(
      await screen.findByRole('button', { name: say.project('edit.open') }),
    ).toBeInTheDocument();
    const side = screen.getByRole('complementary', { name: say.ui('app.trackerSections') });
    expect(
      within(side).getByRole('button', { name: say.project('create.open') }),
    ).toBeInTheDocument();
    expect(screen.getByRole('button', { name: say.project('attribute.add') })).toBeInTheDocument();
  });
});

describe('создание проекта', () => {
  it('описание сверх 320 знаков не отправляется, лишнее названо; заведённый проект открывается', async () => {
    scope('main');
    const user = userEvent.setup();
    renderApp('/tasks', { language: 'ru' });

    await user.click(await screen.findByRole('button', { name: say.project('create.open') }));
    const dialog = await screen.findByRole('dialog', { name: say.project('create.title') });
    await user.type(within(dialog).getByLabelText(say.project('create.keyLabel')), 'new');
    await user.type(within(dialog).getByLabelText(say.project('create.titleLabel')), 'Новый');

    const description = within(dialog).getByLabelText(say.project('description.label'));
    await user.click(description);
    await user.paste('д'.repeat(321));
    expect(description).toHaveAttribute('aria-invalid', 'true');
    expect(
      within(dialog).getByText(say.project('description.over', { count: 1, limit: 320 })),
    ).toBeInTheDocument();
    const submit = within(dialog).getByRole('button', { name: say.project('create.submit') });
    expect(submit).toBeDisabled();

    // Знак стёрт — остаток ноль, и отправка снова возможна.
    await user.type(description, '{Backspace}');
    expect(
      within(dialog).getByText(say.project('description.left', { count: 0, limit: 320 })),
    ).toBeInTheDocument();
    expect(writes).toEqual([]);

    await user.click(submit);
    await waitFor(() => expect(address.current).toBe('/projects/NEW'));
    expect(writes).toEqual([
      {
        method: 'POST',
        path: '/api/v1/projects',
        body: { key: 'new', title: 'Новый', description: 'д'.repeat(320) },
      },
    ]);
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('занятый ключ объяснён словами на обоих языках, окно остаётся открытым', async () => {
    scope('main');
    server.use(
      http.post(`${API}/api/v1/projects`, () =>
        failure('project_key_taken', 409, 'Project key is already taken'),
      ),
    );

    for (const language of ['ru', 'en'] as const) {
      const user = userEvent.setup();
      const { unmount } = renderApp('/tasks', { language });

      await user.click(await screen.findByRole('button', { name: say.project('create.open') }));
      const dialog = await screen.findByRole('dialog', { name: say.project('create.title') });
      await user.type(within(dialog).getByLabelText(say.project('create.keyLabel')), 'DEMO');
      await user.type(within(dialog).getByLabelText(say.project('create.titleLabel')), 'Ещё');
      await user.click(within(dialog).getByRole('button', { name: say.project('create.submit') }));

      expect(
        await within(dialog).findByText(say.errors('project_key_taken'), { exact: false }),
      ).toBeInTheDocument();
      unmount();
    }
    expect(say.errors('project_key_taken', { lng: 'en' })).not.toBe(
      say.errors('project_key_taken', { lng: 'ru' }),
    );
  });

  it('ключ, не прошедший схему, помечает поле ключа и повторяет образец', async () => {
    scope('main');
    server.use(
      http.post(`${API}/api/v1/projects`, () =>
        failure('validation_error', 422, 'Validation failed', {
          errors: [{ loc: ['body', 'key'], msg: 'String should match pattern' }],
        }),
      ),
    );
    const user = userEvent.setup();
    renderApp('/tasks', { language: 'ru' });

    await user.click(await screen.findByRole('button', { name: say.project('create.open') }));
    const dialog = await screen.findByRole('dialog', { name: say.project('create.title') });
    const key = within(dialog).getByLabelText(say.project('create.keyLabel'));
    await user.type(key, '1x');
    await user.type(within(dialog).getByLabelText(say.project('create.titleLabel')), 'Плохой');
    await user.click(within(dialog).getByRole('button', { name: say.project('create.submit') }));

    await waitFor(() => expect(key).toHaveAttribute('aria-invalid', 'true'));
    expect(
      within(dialog).getAllByText(say.project('create.keyHint'), { exact: false }),
    ).toHaveLength(2);
  });
});

describe('правка карточки', () => {
  it('уходит название и описание; отказ по длине читается словами', async () => {
    scope('main');
    server.use(
      http.patch(`${API}/api/v1/projects/DEMO`, async ({ request }) => {
        await remember(request);
        return failure('project_description_too_long', 422, 'Project description is too long');
      }),
    );
    const user = userEvent.setup();
    renderApp('/projects/DEMO', { language: 'ru' });

    await user.click(await screen.findByRole('button', { name: say.project('edit.open') }));
    const dialog = await screen.findByRole('dialog', {
      name: say.project('edit.title', { key: 'DEMO' }),
    });
    const title = within(dialog).getByLabelText(say.project('edit.titleLabel'));
    expect(title).toHaveValue('Демонстрация');
    await user.clear(title);
    await user.type(title, 'Демо');
    await user.click(within(dialog).getByRole('button', { name: say.project('edit.submit') }));

    expect(
      await within(dialog).findByText(say.errors('project_description_too_long')),
    ).toBeInTheDocument();
    expect(writes).toEqual([
      {
        method: 'PATCH',
        path: '/api/v1/projects/DEMO',
        body: { title: 'Демо', description: 'Учебный проект.' },
      },
    ]);
  });
});

describe('атрибуты', () => {
  it('заведение уходит без причины', async () => {
    scope('task');
    const user = userEvent.setup();
    renderApp('/projects/DEMO', { language: 'ru' });

    await user.click(await screen.findByRole('button', { name: say.project('attribute.add') }));
    const dialog = await screen.findByRole('dialog', { name: say.project('attribute.addTitle') });
    expect(within(dialog).queryByLabelText(say.project('attribute.reasonLabel'))).toBeNull();
    await user.type(within(dialog).getByLabelText(say.project('attribute.nameLabel')), 'branch');
    await user.type(within(dialog).getByLabelText(say.project('attribute.valueLabel')), 'main');
    await user.click(
      within(dialog).getByRole('button', { name: say.project('attribute.addSubmit') }),
    );

    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
    expect(writes).toEqual([
      { method: 'PUT', path: '/api/v1/projects/DEMO/attributes/branch', body: { value: 'main' } },
    ]);
  });

  it('изменение без причины не отправляется, с причиной — уходит вместе с ней', async () => {
    scope('task');
    const user = userEvent.setup();
    renderApp('/projects/DEMO', { language: 'ru' });

    await user.click(
      await screen.findByRole('button', {
        name: say.project('attribute.changeLabel', { name: 'repo' }),
      }),
    );
    const dialog = await screen.findByRole('dialog', {
      name: say.project('attribute.changeTitle', { name: 'repo' }),
    });
    const value = within(dialog).getByLabelText(say.project('attribute.valueLabel'));
    expect(value).toHaveValue('github.com/demo');
    await user.clear(value);
    await user.type(value, 'github.com/org/demo');

    const save = within(dialog).getByRole('button', {
      name: say.project('attribute.changeSubmit'),
    });
    await user.click(save);
    const reason = within(dialog).getByLabelText(say.project('attribute.reasonLabel'));
    expect(reason).toBeRequired();
    expect(reason).toHaveAttribute('aria-invalid', 'true');
    expect(within(dialog).getByRole('alert')).toHaveTextContent(
      say.project('attribute.reasonEmpty'),
    );
    expect(writes).toEqual([]);

    await user.type(reason, 'Переехал в организацию');
    await user.click(save);
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
    expect(writes).toEqual([
      {
        method: 'PUT',
        path: '/api/v1/projects/DEMO/attributes/repo',
        body: { value: 'github.com/org/demo', reason: 'Переехал в организацию' },
      },
    ]);
  });

  it('отказ «нужна причина» от бэкенда читается словами на обоих языках', async () => {
    scope('task');
    server.use(
      http.put(`${API}/api/v1/projects/DEMO/attributes/:name`, () =>
        failure(
          'attribute_reason_required',
          422,
          'Changing or removing an attribute requires a reason',
        ),
      ),
    );

    for (const language of ['ru', 'en'] as const) {
      const user = userEvent.setup();
      const { unmount } = renderApp('/projects/DEMO', { language });
      await user.click(await screen.findByRole('button', { name: say.project('attribute.add') }));
      const dialog = await screen.findByRole('dialog', {
        name: say.project('attribute.addTitle'),
      });
      await user.type(within(dialog).getByLabelText(say.project('attribute.nameLabel')), 'REPO');
      await user.type(within(dialog).getByLabelText(say.project('attribute.valueLabel')), 'x');
      await user.click(
        within(dialog).getByRole('button', { name: say.project('attribute.addSubmit') }),
      );
      expect(
        await within(dialog).findByText(say.errors('attribute_reason_required'), { exact: false }),
      ).toBeInTheDocument();
      unmount();
    }
  });

  it('снятие — окно-вопрос с обязательной причиной', async () => {
    scope('task');
    const user = userEvent.setup();
    renderApp('/projects/DEMO', { language: 'ru' });

    await user.click(
      await screen.findByRole('button', {
        name: say.project('attribute.removeLabel', { name: 'repo' }),
      }),
    );
    const dialog = await screen.findByRole('alertdialog', {
      name: say.project('attribute.removeTitle', { name: 'repo' }),
    });
    const confirm = within(dialog).getByRole('button', {
      name: say.project('attribute.removeSubmit'),
    });
    await user.click(confirm);
    expect(within(dialog).getByRole('alert')).toHaveTextContent(
      say.project('attribute.removeReasonEmpty'),
    );
    expect(writes).toEqual([]);

    await user.type(
      within(dialog).getByLabelText(say.project('attribute.reasonLabel')),
      'Не публикуется',
    );
    await user.click(confirm);
    await waitFor(() => expect(screen.queryByRole('alertdialog')).toBeNull());
    expect(writes).toEqual([
      {
        method: 'POST',
        path: '/api/v1/projects/DEMO/attributes/repo/remove',
        body: { reason: 'Не публикуется' },
      },
    ]);
  });
});

describe('заметка в дело проекта', () => {
  it('уходит записью `note` с заголовком из первой строки и подтверждается ссылкой `DEMO#N`', async () => {
    scope('task');
    const user = userEvent.setup();
    renderApp('/projects/DEMO', { language: 'ru' });

    await user.click(await screen.findByRole('button', { name: say.project('note.open') }));
    const form = screen.getByRole('form', { name: say.project('note.formLabel', { key: 'DEMO' }) });
    const field = within(form).getByLabelText(say.project('note.fieldLabel'));
    expect(field).toHaveFocus();
    await user.type(field, 'Релизы по пятницам{Enter}Так договорились.');
    await user.click(within(form).getByRole('button', { name: say.project('note.submit') }));

    const receipt = await screen.findByRole('region', {
      name: say.project('note.receiptLabel', { key: 'DEMO' }),
    });
    expect(within(receipt).getByRole('link', { name: 'DEMO#12' })).toHaveAttribute(
      'href',
      '/projects/DEMO?entry=12',
    );
    expect(writes).toEqual([
      {
        method: 'POST',
        path: '/api/v1/projects/DEMO/entries',
        body: {
          type: 'note',
          title: 'Релизы по пятницам',
          body: 'Релизы по пятницам\nТак договорились.',
        },
      },
    ]);
  });

  it('пустую форму отмена сворачивает и возвращает фокус на кнопку', async () => {
    scope('task');
    const user = userEvent.setup();
    renderApp('/projects/DEMO', { language: 'ru' });

    await user.click(await screen.findByRole('button', { name: say.project('note.open') }));
    await user.click(screen.getByRole('button', { name: say.ui('composer.cancel') }));
    expect(screen.getByRole('button', { name: say.project('note.open') })).toHaveFocus();
  });
});
