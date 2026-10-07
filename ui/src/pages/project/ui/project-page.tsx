import { useTranslation } from 'react-i18next';
import { Link, useParams } from 'react-router';
import { useQuery } from '@tanstack/react-query';
import { projectQueryOptions } from '@/entities/project';
import { ExplanationPanel, HINT_KEYS } from '@/features/manage-onboarding';
import {
  AttributesSection,
  CaseSection,
  HOLDER_SCREEN,
  HolderScreen,
  ProjectMenu,
  useHolderAddress,
  useProjectRights,
  type HolderTabLink,
} from '@/features/manage-project';
import { tasksHref } from '@/features/task-filters';
import { ApiError } from '@/shared/api';
import { useLanguage } from '@/shared/i18n';
import { exactTime } from '@/shared/lib';
import { Callout, QueryState } from '@/shared/ui';
import { ProjectDecisions } from './project-decisions';
import { ProjectDirections } from './project-directions';
import { ProjectOverview } from './project-overview';

/**
 * Экран проекта (UI-174; раскладка вкладками — TRK-618, решение проекта TRK#46): шапка —
 * ключ, название, описание, «Задачи проекта», меню «⋯», — и вкладки «Обзор», «Решения»,
 * «Атрибуты», «Направления», «Дело» под ней. Каркас общий со страницей направления
 * (`HolderScreen`).
 *
 * Всё состояние — в адресе (`useHolderAddress`): `?tab=` называет вкладку, `?entry=N` —
 * раскрытую запись дела, `?attribute=имя` — атрибут, чья история открыта. Без `tab`
 * запись открывает «Дело», атрибут — «Атрибуты»: так ссылки `TRK#7`, квитанции и строка
 * «Решения» карточки задачи доходят до записи без правки построителей ссылок.
 *
 * Действия с проектом (`UI-175`): «Изменить» и «В архив» — в меню «⋯» шапки, «Добавить
 * атрибут», «Изменить» и «Снять» — у атрибутов, «Написать заметку» — у дела. Видны они,
 * когда сеанс известен (`useProjectRights`): наборов токена нет, запись открыта всем.
 *
 * Архивный проект (`UI-176`, `archived_at` из контракта) только читается: правки
 * карточки, атрибутов и заметки на нём нет вовсе, а не «есть и кончается отказом
 * `project_archived`». Вместо них — плашка «в архиве с …», а в меню «⋯» остаётся одно
 * «Восстановить».
 */
export function ProjectPage() {
  const { key = '' } = useParams();
  const project = useQuery(projectQueryOptions(key));
  const rights = useProjectRights();
  const address = useHolderAddress('project');
  const { language } = useLanguage();
  const { t } = useTranslation('project');

  if (project.error instanceof ApiError && project.error.code === 'project_not_found') {
    return (
      <main className={HOLDER_SCREEN}>
        <h1 className="text-title">{t('missingTitle', { key })}</h1>
        <Callout>{t('missingText')}</Callout>
        <Link to="/tasks">{t('backToList')}</Link>
      </main>
    );
  }

  if (project.data === undefined) {
    return (
      <main className={HOLDER_SCREEN}>
        <QueryState query={project} loading={t('loading', { key })} />
      </main>
    );
  }

  const card = project.data;
  // Признак берётся из контракта как есть: интерфейс архив не вычисляет.
  const archivedAt = card.archived_at ?? null;
  const frozen = archivedAt !== null;
  const canWrite = rights.write && !frozen;
  const holder = { kind: 'project', key: card.key } as const;

  // Числа вкладок — из карточки проекта, без своих запросов: действующие решения
  // (статус считает бэкенд), атрибуты и активные направления. У дела числа нет:
  // `meta.total` у дела проекта не считается.
  const tabs: HolderTabLink[] = [
    { tab: 'overview', label: t('tabs.overview') },
    {
      tab: 'decisions',
      label: t('tabs.decisions'),
      count: card.decisions.filter((decision) => decision.status === 'in_force').length,
    },
    { tab: 'attributes', label: t('tabs.attributes'), count: card.attributes.length },
    { tab: 'directions', label: t('tabs.directions'), count: card.directions.length },
    { tab: 'case', label: t('tabs.case') },
  ];

  return (
    <HolderScreen
      // Пояснение экрана — первым блоком (TRK-363). У архивного проекта его нет: текст
      // называет правку и заметки, а они там закрыты.
      explanation={
        frozen ? null : (
          <ExplanationPanel hintKey={HINT_KEYS.project}>{t('explanation.body')}</ExplanationPanel>
        )
      }
      kicker={t('kicker')}
      code={card.key}
      title={card.title}
      description={card.description}
      noDescription={t('noDescription')}
      links={<Link to={tasksHref('', { project: card.key })}>{t('tasks')}</Link>}
      menu={rights.manage ? <ProjectMenu project={card} archived={frozen} /> : null}
      notice={
        // Архив сказан словами под шапкой, а не одним цветом: почему на экране нет ни
        // одной кнопки правки, человек читает здесь же.
        frozen ? (
          <Callout>
            {t(rights.manage ? 'archived.notice' : 'archived.noticeReadOnly', {
              when: exactTime(archivedAt, language),
            })}
          </Callout>
        ) : null
      }
      tabsLabel={t('tabs.label')}
      tabs={tabs}
      current={address.tab}
      tabHref={address.tabHref}
    >
      {address.tab === 'decisions' ? (
        <ProjectDecisions
          projectKey={card.key}
          decisions={card.decisions}
          entryHref={address.entryHref}
        />
      ) : address.tab === 'attributes' ? (
        <AttributesSection
          holder={holder}
          attributes={card.attributes}
          canWrite={canWrite}
          open={address.attribute}
          onOpenChange={address.rememberAttribute}
        />
      ) : address.tab === 'directions' ? (
        <ProjectDirections projectKey={card.key} canWrite={canWrite} />
      ) : address.tab === 'case' ? (
        <CaseSection
          holder={holder}
          canWrite={canWrite}
          openAt={address.openAt}
          onOpenChange={address.rememberEntry}
        />
      ) : (
        <ProjectOverview
          projectKey={card.key}
          directions={card.directions}
          decisions={card.decisions}
          entryHref={address.entryHref}
          tabHref={address.tabHref}
        />
      )}
    </HolderScreen>
  );
}
