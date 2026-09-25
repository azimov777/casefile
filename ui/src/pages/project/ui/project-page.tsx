import { useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, useParams, useSearchParams } from 'react-router';
import { useQuery } from '@tanstack/react-query';
import { projectQueryOptions } from '@/entities/project';
import { EditProject, ProjectArchiving, useProjectRights } from '@/features/manage-project';
import { tasksHref } from '@/features/task-filters';
import { ApiError } from '@/shared/api';
import { useLanguage } from '@/shared/i18n';
import { exactTime, readEntryNo } from '@/shared/lib';
import { Callout, Markdown, QueryState } from '@/shared/ui';
import { ProjectAttributes } from './project-attributes';
import { ProjectCase } from './project-case';

/** Колонка экрана: та же ширина и тот же шаг, что у карточки задачи. */
const SCREEN = 'flex max-w-(--ui-page-max) flex-col gap-4';

/**
 * Экран проекта на чтение (UI-174, `docs/CONCEPT.md`, 3): карточка — ключ, название,
 * описание, — атрибуты с историей по клику и опись дела проекта с телами по клику.
 *
 * Всё состояние — в адресе: `?entry=N` называет раскрытую запись дела, `?attribute=имя`
 * — атрибут, чья история открыта. Ссылку можно переслать, перезагрузка возвращает тот
 * же экран.
 *
 * Действия с проектом (`UI-175`) стоят там, где лежит то, что они меняют: «Изменить»
 * — у карточки, «Добавить атрибут», «Изменить» и «Снять» — у атрибутов, «Написать
 * заметку» — у дела. Какие из них видны, решает набор ключа (`useProjectRights`):
 * карточку правит только `main`, атрибуты и заметки — любой.
 *
 * Архивный проект (`UI-176`, `archived_at` из контракта) только читается: правки
 * карточки, атрибутов и заметки на нём нет вовсе, а не «есть и кончается отказом
 * `project_archived`». Вместо них — плашка «в архиве с …», а кнопка «В архив» набора
 * `main` становится «Восстановить» на том же месте (`ProjectArchiving`).
 */
export function ProjectPage() {
  const { key = '' } = useParams();
  const [searchParams, setSearchParams] = useSearchParams();
  const project = useQuery(projectQueryOptions(key));
  const rights = useProjectRights();
  const { language } = useLanguage();
  const { t } = useTranslation('project');

  const openAt = readEntryNo(searchParams.get('entry'));
  const attribute = searchParams.get('attribute');

  /**
   * Правка одного параметра адреса, остальные — как были. `replace`, а не новая
   * запись истории: раскрытие записи или атрибута — не «страница», и «назад» после
   * трёх кликов ведёт туда, откуда человек пришёл, а не сворачивает их по одному
   * (то же правило, что у карточки задачи, `task-page.tsx`, `rememberOpen`).
   */
  const remember = useCallback(
    (name: 'entry' | 'attribute', value: string | null) => {
      setSearchParams(
        (current) => {
          const updated = new URLSearchParams(current);
          if (value === null) updated.delete(name);
          else updated.set(name, value);
          return updated;
        },
        { replace: true },
      );
    },
    [setSearchParams],
  );

  const rememberEntry = useCallback(
    (no: number | null) => remember('entry', no === null ? null : String(no)),
    [remember],
  );
  const rememberAttribute = useCallback(
    (name: string | null) => remember('attribute', name),
    [remember],
  );

  if (project.error instanceof ApiError && project.error.code === 'project_not_found') {
    return (
      <main className={SCREEN}>
        <h1 className="text-title">{t('missingTitle', { key })}</h1>
        <Callout>{t('missingText')}</Callout>
        <Link to="/tasks">{t('backToList')}</Link>
      </main>
    );
  }

  if (project.data === undefined) {
    return (
      <main className={SCREEN}>
        <QueryState query={project} loading={t('loading', { key })} />
      </main>
    );
  }

  const card = project.data;
  // Признак берётся из контракта как есть: интерфейс архив не вычисляет.
  const archivedAt = card.archived_at ?? null;
  const frozen = archivedAt !== null;
  const canWrite = rights.write && !frozen;

  return (
    <main className={SCREEN}>
      <header className="flex flex-col gap-2">
        <p className="text-label font-semibold tracking-caps text-faint uppercase">{t('kicker')}</p>
        {/* Ключ — идентификатор контракта, моноширинным; название пишет агент или
            человек, и оно переносится где угодно: длину чужой строки интерфейс не
            выбирает, а горизонтальной прокрутки на телефоне быть не должно. */}
        <h1 className="flex flex-wrap items-baseline gap-x-3 text-title wrap-anywhere">
          <span className="font-mono">{card.key}</span>
          <span>{card.title}</span>
        </h1>
        {/* Описание — короткое «что это» (до 320 знаков, `../docs/CONCEPT.md`, 3.2), в
            markdown, как и всё, что пишут агенты. Пустое — сказано словами. */}
        {card.description.trim() === '' ? (
          <p className="text-muted italic">{t('noDescription')}</p>
        ) : (
          <div className="max-w-(--ui-text-max)">
            <Markdown>{card.description}</Markdown>
          </div>
        )}
        {/* Задачи проекта — тот же адрес, что у строки проекта в панели. Правка карточки
            стоит в той же строке: она меняет то, что написано прямо над ней. */}
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
          <Link to={tasksHref('', { project: card.key })}>{t('tasks')}</Link>
          {rights.manage && !frozen ? <EditProject project={card} /> : null}
          {rights.manage ? <ProjectArchiving projectKey={card.key} archived={frozen} /> : null}
        </div>
        {/* Архив сказан словами под карточкой, а не одним цветом: почему на экране нет
            ни одной кнопки правки, человек читает здесь же. */}
        {frozen ? (
          <Callout>
            {t(rights.manage ? 'archived.notice' : 'archived.noticeReadOnly', {
              when: exactTime(archivedAt, language),
            })}
          </Callout>
        ) : null}
      </header>

      {/*
       * Две колонки на точке `card`, как у карточки задачи, и каждая своим потоком.
       * Атрибуты стоят первыми в разметке: это то, что о проекте верно сейчас, и на
       * узком экране они встают над делом, а не за ним. Доли 2:3 — атрибуты это
       * короткие пары «имя → значение», дело — таблица описи.
       */}
      <div className="flex flex-col gap-4 card:flex-row card:items-start">
        <div className="flex flex-col gap-4 card:min-w-0 card:flex-[2_1_0]">
          <ProjectAttributes
            projectKey={card.key}
            attributes={card.attributes}
            canWrite={canWrite}
            open={attribute}
            onOpenChange={rememberAttribute}
          />
        </div>
        <div className="flex flex-col gap-4 card:min-w-0 card:flex-[3_1_0]">
          <ProjectCase
            projectKey={card.key}
            canWrite={canWrite}
            openAt={openAt}
            onOpenChange={rememberEntry}
          />
        </div>
      </div>
    </main>
  );
}
