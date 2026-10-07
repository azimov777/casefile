import { useTranslation } from 'react-i18next';
import { Link, useParams } from 'react-router';
import { useQuery } from '@tanstack/react-query';
import { areaQueryOptions } from '@/entities/area';
import { projectQueryOptions } from '@/entities/project';
import {
  AttributesSection,
  CaseSection,
  AreaMenu,
  HOLDER_SCREEN,
  HolderScreen,
  useHolderAddress,
  useProjectRights,
  type HolderTabLink,
} from '@/features/manage-project';
import { TaskCounters, tasksHref } from '@/features/task-filters';
import { ApiError } from '@/shared/api';
import { useLanguage } from '@/shared/i18n';
import { exactTime, projectHref } from '@/shared/lib';
import { Callout, QueryState } from '@/shared/ui';

/** Отказы, после которых области по этому адресу нет: проекта или области. */
const MISSING: readonly string[] = ['area_not_found', 'project_not_found'];

/**
 * Страница области (TRK-557, TRK#16, ч. 4) — на том же каркасе, что экран проекта
 * (`HolderScreen`, TRK-618, решение TRK#46): шапка — адрес, название, описание, ссылки на
 * проект и на задачи области, меню «⋯», — и вкладки «Атрибуты» и «Дело». «Обзора» у
 * области нет: без параметра открывается «Дело».
 *
 * Адрес страницы — под проектом, как путь API: `/projects/TRK/areas/promotion`.
 * Состояние — в адресе, как у проекта (`useHolderAddress`): `?tab=` — вкладка, `?entry=N`
 * — раскрытая запись дела (сюда ведёт ссылка `TRK/promotion#3`), `?attribute=имя` —
 * открытая история атрибута.
 *
 * «Изменить», «В архив» и «Восстановить» — в меню «⋯» шапки, атрибуты — у атрибутов,
 * запись — у дела; в дело человек пишет заметку или решение. Архивная область и
 * область архивного проекта только читаются: правок нет вовсе, а не «есть и кончаются
 * отказом». Восстановить область архивного проекта нельзя (`project_archived`):
 * сначала восстанавливают проект, и плашка говорит это словами — меню у такой страницы нет.
 */
export function AreaPage() {
  const params = useParams();
  /*
   * Адрес в каноническом регистре — ключ проекта заглавными, ключ области строчными,
   * как их хранит бэкенд: по этому адресу строится ключ запроса, и правка из окна
   * перечитывает его адресом из ответа. Набранный руками `/projects/trk/areas/Promo`
   * иначе дал бы второй ключ той же области, который правка не задела бы.
   */
  const key = (params.key ?? '').toUpperCase();
  const address = `${key}/${(params.area ?? '').toLowerCase()}`;
  const area = useQuery(areaQueryOptions(address));
  const project = useQuery(projectQueryOptions(key));
  const rights = useProjectRights();
  const place = useHolderAddress('area');
  const { language } = useLanguage();
  const { t } = useTranslation('area');

  if (area.error instanceof ApiError && MISSING.includes(area.error.code)) {
    return (
      <main className={HOLDER_SCREEN}>
        <h1 className="text-title wrap-anywhere">{t('page.missingTitle', { address })}</h1>
        <Callout>{t('page.missingText')}</Callout>
        <Link to={projectHref(key)}>{t('page.backToProject', { key })}</Link>
      </main>
    );
  }

  if (area.data === undefined) {
    return (
      <main className={HOLDER_SCREEN}>
        <QueryState query={area} loading={t('page.loading', { address })} />
      </main>
    );
  }

  const card = area.data;
  // Оба признака — из контракта как есть: интерфейс архив не вычисляет. Пока карточка
  // проекта не пришла, правок нет: проект мог оказаться архивным.
  const archivedAt = card.archived_at;
  const projectArchivedAt = project.data?.archived_at ?? null;
  const projectKnown = project.data !== undefined;
  const projectFrozen = projectArchivedAt !== null;
  const frozen = archivedAt !== null || projectFrozen;
  const canWrite = rights.write && projectKnown && !frozen;
  const canArchive = rights.manage && projectKnown && !projectFrozen;
  const holder = { kind: 'area', key: card.address } as const;

  const tabs: HolderTabLink[] = [
    { tab: 'attributes', label: t('tabs.attributes'), count: card.attributes.length },
    { tab: 'case', label: t('tabs.case') },
  ];

  return (
    <HolderScreen
      kicker={t('page.kicker')}
      code={card.address}
      title={card.title}
      description={card.description}
      noDescription={t('page.noDescription')}
      links={
        // Проект и задачи области — ссылками. Задачи — список с отбором `area`,
        // тем же условием, каким их отбирает агент.
        <>
          <Link to={projectHref(card.project_key)}>
            {t('page.project', { key: card.project_key })}
          </Link>
          <Link to={tasksHref('', { project: card.project_key, area: card.address })}>
            {t('page.tasks')}
          </Link>
        </>
      }
      counters={<TaskCounters project={card.project_key} area={card.address} />}
      menu={
        <AreaMenu
          area={card}
          canEdit={canWrite}
          canArchive={canArchive}
          archived={archivedAt !== null}
        />
      }
      notice={
        // Архив сказан словами под шапкой: почему на странице нет ни одной кнопки правки,
        // человек читает здесь же.
        projectFrozen ? (
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
        ) : null
      }
      tabsLabel={t('tabs.label')}
      tabs={tabs}
      current={place.tab}
      tabHref={place.tabHref}
    >
      {place.tab === 'attributes' ? (
        <AttributesSection
          holder={holder}
          attributes={card.attributes}
          canWrite={canWrite}
          open={place.attribute}
          onOpenChange={place.rememberAttribute}
        />
      ) : (
        <CaseSection
          holder={holder}
          canWrite={canWrite}
          openAt={place.openAt}
          onOpenChange={place.rememberEntry}
        />
      )}
    </HolderScreen>
  );
}
