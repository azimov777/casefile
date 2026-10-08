import { useRef, useState, type ReactNode, type RefObject } from 'react';
import { http } from 'msw';
import { MemoryRouter } from 'react-router';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import userEvent from '@testing-library/user-event';
import { render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it } from 'vitest';
import { API, data, areaDetail, failure, projectDetail } from '@testing/msw/responses';
import { server } from '@testing/msw/server';
import { say } from '@testing/say';
import { i18n } from '@/shared/i18n';
import { setToken } from '@/shared/api';
import { ProjectArchiving } from './archive-project';
import { AreaArchivingDialog, EditAreaDialog } from './area-dialogs';
import { EditProject } from './edit-project';
import { areaMenuActions, projectMenuActions } from '../model/menu-actions';

/*
 * Меню «⋯» экрана проекта и страницы области (TRK-618): какие пункты в нём стоят и
 * что делают окна, которые они открывают.
 *
 * Окна проверяются открытыми сами по себе, без меню: `Popover` Radix в jsdom раскрывается
 * секундами (замер TRK-618: около 9 с на одно открытие голой панели; `TRK/ui-testing#51`,
 * «Панель `Popover` в jsdom открывается десятки секунд»). Путь «⋯» → пункт → окно → `Esc`
 * → фокус на «⋯» проверяют сквозные `e2e/project-actions.spec.ts` и
 * `e2e/project-archive.spec.ts` в настоящем браузере.
 */

/** Имя кнопки «⋯» рядом с окном: сюда окно возвращает фокус. */
const MENU = 'menu';

const ADDRESS = 'DEMO/promotion';
const AREA_PATH = '/api/v1/projects/DEMO/areas/promotion';

/** Запросы записи прогона: метод, путь и тело — по ним видно, что ушло и чего не ушло. */
let writes: { method: string; path: string; body: unknown }[] = [];

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
    http.patch(`${API}/api/v1/projects/DEMO`, async ({ request }) => {
      await remember(request);
      return data(projectDetail('DEMO'));
    }),
    http.post(`${API}/api/v1/projects/DEMO/archive`, async ({ request }) => {
      await remember(request);
      return data(projectDetail('DEMO', { archived_at: '2026-09-20T10:00:00Z' }));
    }),
    http.post(`${API}/api/v1/projects/DEMO/restore`, async ({ request }) => {
      await remember(request);
      return data(projectDetail('DEMO'));
    }),
    http.patch(`${API}${AREA_PATH}`, async ({ request }) => {
      await remember(request);
      return data(areaDetail(ADDRESS));
    }),
    http.post(`${API}${AREA_PATH}/archive`, async ({ request }) => {
      await remember(request);
      return data(areaDetail(ADDRESS, { archived_at: '2026-10-06T10:00:00Z' }));
    }),
  );
});

/**
 * Окно, открытое пунктом меню: рядом стоит кнопка «⋯», на которую оно возвращает фокус.
 * Окно получает её ссылкой (`returnFocus`), а закрытое — убирается, как у меню.
 */
function Opened({
  children,
}: {
  children: (props: {
    open: boolean;
    onOpenChange: (open: boolean) => void;
    returnFocus: RefObject<HTMLButtonElement | null>;
  }) => ReactNode;
}) {
  const [open, setOpen] = useState(true);
  const menu = useRef<HTMLButtonElement>(null);
  return (
    <>
      <button type="button" ref={menu} aria-label={MENU} />
      {children({ open, onOpenChange: setOpen, returnFocus: menu })}
    </>
  );
}

function renderOpened(
  children: Parameters<typeof Opened>[0]['children'],
  language: 'ru' | 'en' = 'ru',
) {
  void i18n.changeLanguage(language);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <Opened>{children}</Opened>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('пункты меню', () => {
  it('у активного проекта — «Изменить» и «В архив», у архивного — одно «Восстановить»', () => {
    expect(projectMenuActions(false)).toEqual(['edit', 'archive']);
    expect(projectMenuActions(true)).toEqual(['restore']);
  });

  it('у области пункты идут за правами страницы; без прав меню пустое', () => {
    expect(areaMenuActions({ canEdit: true, canArchive: true, archived: false })).toEqual([
      'edit',
      'archive',
    ]);
    // Архивная область активного проекта: правки нет, есть «Восстановить».
    expect(areaMenuActions({ canEdit: false, canArchive: true, archived: true })).toEqual([
      'restore',
    ]);
    // Область архивного проекта: ни правки, ни архива, ни восстановления.
    expect(areaMenuActions({ canEdit: false, canArchive: false, archived: false })).toEqual([]);
    expect(areaMenuActions({ canEdit: false, canArchive: false, archived: true })).toEqual([]);
  });
});

describe('окно «Изменить» проекта', () => {
  it('уходит название и описание; отказ по длине читается словами', async () => {
    server.use(
      http.patch(`${API}/api/v1/projects/DEMO`, async ({ request }) => {
        await remember(request);
        return failure('project_description_too_long', 422, 'Project description is too long');
      }),
    );
    const user = userEvent.setup();
    renderOpened((place) => (
      <EditProject project={projectDetail('DEMO', { description: 'Учебный проект.' })} {...place} />
    ));

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

  it('после закрытия фокус возвращается на «⋯», а не падает на `body`', async () => {
    const user = userEvent.setup();
    renderOpened((place) => <EditProject project={projectDetail('DEMO')} {...place} />);

    const dialog = await screen.findByRole('dialog');
    await user.click(within(dialog).getByRole('button', { name: say.project('cancel') }));
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
    expect(screen.getByRole('button', { name: MENU })).toHaveFocus();
  });
});

describe('окна архива и восстановления проекта (UI-176)', () => {
  it('архив без причины не отправляется и говорит почему; с причиной уходит `reason`', async () => {
    const user = userEvent.setup();
    renderOpened((place) => <ProjectArchiving projectKey="DEMO" archived={false} {...place} />);

    const dialog = await screen.findByRole('alertdialog', {
      name: say.project('archive.title', { key: 'DEMO' }),
    });
    const submit = within(dialog).getByRole('button', { name: say.project('archive.submit') });

    // Одни пробелы — та же пустота, что и ничего.
    const reason = within(dialog).getByLabelText(say.project('archive.reasonLabel'));
    await user.type(reason, '   ');
    await user.click(submit);
    expect(within(dialog).getByRole('alert')).toHaveTextContent(say.project('archive.reasonEmpty'));
    expect(reason).toHaveAttribute('aria-invalid', 'true');
    expect(writes).toEqual([]);

    await user.type(reason, 'Работа переехала в CORE');
    await user.click(submit);
    await waitFor(() => expect(screen.queryByRole('alertdialog')).toBeNull());
    expect(writes).toEqual([
      {
        method: 'POST',
        path: '/api/v1/projects/DEMO/archive',
        body: { reason: 'Работа переехала в CORE' },
      },
    ]);
    // Фокус — на «⋯»: кнопке, которая переживает архив, а не на исчезнувшем пункте.
    expect(screen.getByRole('button', { name: MENU })).toHaveFocus();
  });

  it('«Восстановить» — обычное окно, а не `alertdialog`; без причины не уходит, с причиной — на `/restore`', async () => {
    const user = userEvent.setup();
    renderOpened((place) => <ProjectArchiving projectKey="DEMO" archived {...place} />);

    // Восстановление ничего не замораживает — обычное окно, а не `alertdialog`.
    const dialog = await screen.findByRole('dialog', {
      name: say.project('restore.title', { key: 'DEMO' }),
    });
    await user.click(within(dialog).getByRole('button', { name: say.project('restore.submit') }));
    expect(within(dialog).getByRole('alert')).toHaveTextContent(say.project('restore.reasonEmpty'));
    expect(writes).toEqual([]);

    await user.type(
      within(dialog).getByLabelText(say.project('restore.reasonLabel')),
      'Вернулись к работе',
    );
    await user.click(within(dialog).getByRole('button', { name: say.project('restore.submit') }));
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
    expect(writes).toEqual([
      {
        method: 'POST',
        path: '/api/v1/projects/DEMO/restore',
        body: { reason: 'Вернулись к работе' },
      },
    ]);
  });

  it('отказ бэкенда читается словами словаря, окно остаётся открытым', async () => {
    server.use(
      http.post(`${API}/api/v1/projects/DEMO/archive`, () =>
        failure('project_archived', 409, 'Project is archived'),
      ),
    );
    const user = userEvent.setup();
    renderOpened(
      (place) => <ProjectArchiving projectKey="DEMO" archived={false} {...place} />,
      'en',
    );

    const dialog = await screen.findByRole('alertdialog');
    await user.type(within(dialog).getByLabelText(say.project('archive.reasonLabel')), 'Done');
    await user.click(within(dialog).getByRole('button', { name: say.project('archive.submit') }));
    expect(await within(dialog).findByText(say.errors('project_archived'))).toBeInTheDocument();
  });
});

describe('окна области из меню', () => {
  it('правка названия и описания уходит `PATCH` по адресу области, фокус — на «⋯»', async () => {
    const user = userEvent.setup();
    renderOpened((place) => (
      <EditAreaDialog
        area={{
          address: ADDRESS,
          title: 'Популяризация',
          description: 'Каталоги, публикации и **день запуска**.',
        }}
        {...place}
      />
    ));

    const dialog = await screen.findByRole('dialog', {
      name: say.area('edit.title', { address: ADDRESS }),
    });
    const title = within(dialog).getByLabelText(say.area('edit.titleLabel'));
    await user.clear(title);
    await user.type(title, 'Продвижение');
    await user.click(within(dialog).getByRole('button', { name: say.area('edit.submit') }));

    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
    expect(writes).toEqual([
      {
        method: 'PATCH',
        path: AREA_PATH,
        body: { title: 'Продвижение', description: 'Каталоги, публикации и **день запуска**.' },
      },
    ]);
    expect(screen.getByRole('button', { name: MENU })).toHaveFocus();
  });

  it('архив без причины не уходит и говорит почему; с причиной — `reason`', async () => {
    const user = userEvent.setup();
    renderOpened((place) => <AreaArchivingDialog address={ADDRESS} archived={false} {...place} />);

    const dialog = await screen.findByRole('alertdialog', {
      name: say.area('archive.title', { address: ADDRESS }),
    });
    const submit = within(dialog).getByRole('button', { name: say.area('archive.submit') });
    await user.click(submit);
    expect(within(dialog).getByRole('alert')).toHaveTextContent(say.area('archive.reasonEmpty'));
    expect(writes).toEqual([]);

    await user.type(
      within(dialog).getByLabelText(say.area('archive.reasonLabel')),
      'Запуск прошёл',
    );
    await user.click(submit);
    await waitFor(() => expect(screen.queryByRole('alertdialog')).toBeNull());
    expect(writes).toEqual([
      { method: 'POST', path: `${AREA_PATH}/archive`, body: { reason: 'Запуск прошёл' } },
    ]);
  });
});
