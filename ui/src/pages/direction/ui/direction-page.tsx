import { useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, useParams, useSearchParams } from 'react-router';
import { useQuery } from '@tanstack/react-query';
import { directionQueryOptions } from '@/entities/direction';
import { projectQueryOptions } from '@/entities/project';
import {
  AttributesSection,
  CaseSection,
  DirectionArchiving,
  EditDirection,
  useProjectRights,
} from '@/features/manage-project';
import { tasksHref } from '@/features/task-filters';
import { ApiError } from '@/shared/api';
import { useLanguage } from '@/shared/i18n';
import { exactTime, projectHref, readEntryNo } from '@/shared/lib';
import { Callout, Markdown, QueryState } from '@/shared/ui';

/** Колонка экрана: та же ширина и тот же шаг, что у экрана проекта. */
const SCREEN = 'flex max-w-(--ui-page-max) flex-col gap-4';

/** Отказы, после которых направления по этому адресу нет: проекта или направления. */
const MISSING: readonly string[] = ['direction_not_found', 'project_not_found'];

/**
 * Страница направления (TRK-557, TRK#16, ч. 4) — по образцу экрана проекта: карточка —
 * адрес, название, описание, — атрибуты с историей по клику, дело направления описью с
 * телами по клику и задачи направления ссылкой в список с отбором по нему.
 *
 * Адрес страницы — под проектом, как путь API: `/projects/TRK/directions/promotion`.
 * Состояние — в адресе, как у проекта: `?entry=N` — раскрытая запись дела (сюда ведёт
 * ссылка `TRK/promotion#3`), `?attribute=имя` — открытая история атрибута.
 *
 * Действия стоят там, где лежит то, что они меняют: «Изменить», «В архив» и
 * «Восстановить» — у карточки, атрибуты — у атрибутов, запись — у дела; в дело человек
 * пишет заметку или решение. Архивное направление и направление архивного проекта
 * только читаются: правок нет вовсе, а не «есть и кончаются отказом». Восстановить
 * направление архивного проекта нельзя (`project_archived`): сначала восстанавливают
 * проект, и плашка говорит это словами.
 */
export function DirectionPage() {
  const params = useParams();
  /*
   * Адрес в каноническом регистре — ключ проекта заглавными, ключ направления строчными,
   * как их хранит бэкенд: по этому адресу строится ключ запроса, и правка из окна
   * перечитывает его адресом из ответа. Набранный руками `/projects/trk/directions/Promo`
   * иначе дал бы второй ключ того же направления, который правка не задела бы.
   */
  const key = (params.key ?? '').toUpperCase();
  const address = `${key}/${(params.direction ?? '').toLowerCase()}`;
  const [searchParams, setSearchParams] = useSearchParams();
  const direction = useQuery(directionQueryOptions(address));
  const project = useQuery(projectQueryOptions(key));
  const rights = useProjectRights();
  const { language } = useLanguage();
  const { t } = useTranslation('direction');

  const openAt = readEntryNo(searchParams.get('entry'));
  const attribute = searchParams.get('attribute');

  /** Правка одного параметра адреса, остальные — как были; `replace` — как у проекта. */
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

  if (direction.error instanceof ApiError && MISSING.includes(direction.error.code)) {
    return (
      <main className={SCREEN}>
        <h1 className="text-title wrap-anywhere">{t('page.missingTitle', { address })}</h1>
        <Callout>{t('page.missingText')}</Callout>
        <Link to={projectHref(key)}>{t('page.backToProject', { key })}</Link>
      </main>
    );
  }

  if (direction.data === undefined) {
    return (
      <main className={SCREEN}>
        <QueryState query={direction} loading={t('page.loading', { address })} />
      </main>
    );
  }

  const card = direction.data;
  // Оба признака — из контракта как есть: интерфейс архив не вычисляет. Пока карточка
  // проекта не пришла, правок нет: проект мог оказаться архивным.
  const archivedAt = card.archived_at;
  const projectArchivedAt = project.data?.archived_at ?? null;
  const projectKnown = project.data !== undefined;
  const projectFrozen = projectArchivedAt !== null;
  const frozen = archivedAt !== null || projectFrozen;
  const canWrite = rights.write && projectKnown && !frozen;
  const canArchive = rights.manage && projectKnown && !projectFrozen;
  const holder = { kind: 'direction', key: card.address } as const;

  return (
    <main className={SCREEN}>
      <header className="flex flex-col gap-2">
        <p className="text-label font-semibold tracking-caps text-faint uppercase">
          {t('page.kicker')}
        </p>
        {/* Адрес — идентификатор контракта, моноширинным; название переносится где
            угодно: горизонтальной прокрутки на телефоне быть не должно. */}
        <h1 className="flex flex-wrap items-baseline gap-x-3 text-title wrap-anywhere">
          <span className="font-mono">{card.address}</span>
          <span>{card.title}</span>
        </h1>
        {/* Описание — короткое «что это» (до 320 знаков, `../docs/CONCEPT.md`, 3.7); оно
            едет в карточке каждой задачи направления. Пустое — сказано словами. */}
        {card.description.trim() === '' ? (
          <p className="text-muted italic">{t('page.noDescription')}</p>
        ) : (
          <div className="max-w-(--ui-text-max)">
            <Markdown>{card.description}</Markdown>
          </div>
        )}
        {/* Проект и задачи направления — ссылками; правка карточки — в той же строке:
            она меняет то, что написано прямо над ней. Задачи — список с отбором
            `direction`, тем же условием, каким их отбирает агент. */}
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
          <Link to={projectHref(card.project_key)}>
            {t('page.project', { key: card.project_key })}
          </Link>
          <Link to={tasksHref('', { project: card.project_key, direction: card.address })}>
            {t('page.tasks')}
          </Link>
          {canWrite ? <EditDirection direction={card} /> : null}
          {canArchive ? (
            <DirectionArchiving address={card.address} archived={archivedAt !== null} />
          ) : null}
        </div>
        {/* Архив сказан словами под карточкой: почему на странице нет ни одной кнопки
            правки, человек читает здесь же. */}
        {projectFrozen ? (
          <Callout>
            {t('page.projectArchived', {
              key: card.project_key,
              when: exactTime(projectArchivedAt, language),
            })}
          </Callout>
        ) : archivedAt !== null ? (
          <Callout>
            {t(rights.manage ? 'page.archived' : 'page.archivedReadOnly', {
              when: exactTime(archivedAt, language),
            })}
          </Callout>
        ) : null}
      </header>

      {/* Две колонки на точке `card`, как у экрана проекта: атрибуты первыми в разметке
          — на узком экране они встают над делом, а не за ним. */}
      <div className="flex flex-col gap-4 card:flex-row card:items-start">
        <div className="flex flex-col gap-4 card:min-w-0 card:flex-[2_1_0]">
          <AttributesSection
            holder={holder}
            attributes={card.attributes}
            canWrite={canWrite}
            open={attribute}
            onOpenChange={rememberAttribute}
          />
        </div>
        <div className="flex flex-col gap-4 card:min-w-0 card:flex-[3_1_0]">
          <CaseSection
            holder={holder}
            canWrite={canWrite}
            openAt={openAt}
            onOpenChange={rememberEntry}
          />
        </div>
      </div>
    </main>
  );
}
