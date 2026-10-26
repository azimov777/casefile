import { useId, useState, type FormEvent, type ReactNode } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { bootstrapQueryOptions } from '@/entities/session';
import { ApiError } from '@/shared/api';
import { errorMessage } from '@/shared/errors';
import { Button, Callout, Dialog, QueryState } from '@/shared/ui';
import {
  PROJECT_ACCESS_MODES,
  projectAccessQueryOptions,
  type ProjectAccess,
  type ProjectAccessMode,
} from '../api/access';
import { useSetProjectAccess } from '../model/use-access-actions';

/**
 * Окно «Проекты агента»: какие проекты открыты этому агенту (решение владельца
 * TRK~28#6, выбор «A»). Три режима: «все, включая новые» (умолчание), «все, кроме
 * перечисленных», «только перечисленные».
 *
 * Список проектов — из первого кадра (`bootstrap.projects`, без архивных: закрытый
 * проект и так исчезает из списков агента). Ключ, который в режиме уже стоит, а в
 * первом кадре его нет (проект ушёл в архив), остаётся в списке отдельной строкой —
 * иначе сохранение молча стёрло бы его.
 *
 * Права решает бэкенд (`agent_owned_by_another`, `account_required`); экран прячет
 * кнопку у того, кому отказ очевиден, а пришедший всё же отказ объясняет словами.
 */
export function ProjectsDialog({
  participant,
  open,
  onOpenChange,
  trigger,
}: {
  participant: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  trigger: ReactNode;
}) {
  const { t } = useTranslation('access');

  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      trigger={trigger}
      title={t('projects.title', { name: participant })}
      description={t('projects.intro')}
      closeLabel={t('close')}
    >
      <ProjectsLoader participant={participant} onClose={() => onOpenChange(false)} />
    </Dialog>
  );
}

/** Ждёт текущий режим агента и отдаёт его форме, которая рождается заново на каждый заход. */
function ProjectsLoader({ participant, onClose }: { participant: string; onClose: () => void }) {
  const access = useQuery(projectAccessQueryOptions(participant));
  const { t } = useTranslation('access');

  return (
    <>
      <QueryState query={access} loading={t('projects.loading')} compact />
      {access.data === undefined ? null : (
        <ProjectsForm participant={participant} current={access.data} onClose={onClose} />
      )}
    </>
  );
}

function ProjectsForm({
  participant,
  current,
  onClose,
}: {
  participant: string;
  current: ProjectAccess;
  onClose: () => void;
}) {
  const bootstrap = useQuery(bootstrapQueryOptions());
  const save = useSetProjectAccess();
  const [mode, setMode] = useState<ProjectAccessMode>(current.mode);
  const [chosen, setChosen] = useState<string[]>(current.projects);
  const groupName = useId();
  const { t } = useTranslation('access');

  const known = (bootstrap.data?.projects ?? []).map((project) => ({
    key: project.key,
    title: project.title,
  }));
  const extra = current.projects
    .filter((key) => !known.some((project) => project.key === key))
    .map((key) => ({ key, title: '' }));
  const projects = [...known, ...extra];

  function changeMode(next: ProjectAccessMode) {
    if (next === mode) return;
    setMode(next);
    // «Закрыть» и «открыть» — противоположные смыслы одного списка: отметки из одного
    // режима, перенесённые в другой, поменяли бы доступ на обратный.
    setChosen(next === current.mode ? current.projects : []);
  }

  function toggle(key: string, checked: boolean) {
    setChosen(checked ? [...chosen, key] : chosen.filter((item) => item !== key));
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    save.mutate(
      { participant, mode, projects: mode === 'all' ? [] : chosen },
      { onSuccess: onClose },
    );
  }

  const listed = mode !== 'all';
  const ownedByAnother =
    save.error instanceof ApiError && save.error.code === 'agent_owned_by_another';

  return (
    <form className="flex flex-col gap-4" onSubmit={submit} noValidate>
      <fieldset className="flex min-w-0 flex-col gap-2 border-0 p-0">
        <legend className="text-meta text-muted">{t('projects.modeLegend')}</legend>
        {PROJECT_ACCESS_MODES.map((option) => (
          <label key={option} className="flex cursor-pointer items-baseline gap-2">
            <input
              type="radio"
              name={groupName}
              value={option}
              checked={mode === option}
              onChange={() => changeMode(option)}
            />
            <span className="flex max-w-(--ui-text-max) flex-col">
              <span className="text-body">{t(`projects.mode.${option}.label`)}</span>
              <span className="text-meta text-muted">{t(`projects.mode.${option}.hint`)}</span>
            </span>
          </label>
        ))}
      </fieldset>

      {listed ? (
        <fieldset className="flex min-w-0 flex-col gap-1 border-0 p-0">
          <legend className="text-meta text-muted">
            {mode === 'except' ? t('projects.closeLegend') : t('projects.openLegend')}
          </legend>
          <QueryState query={bootstrap} loading={t('projects.loadingProjects')} compact />
          {projects.length === 0 && bootstrap.isSuccess ? (
            <p className="text-body text-muted">{t('projects.none')}</p>
          ) : null}
          {projects.map((project) => (
            <label
              key={project.key}
              className="flex min-h-(--ui-control-sm) cursor-pointer items-center gap-2"
            >
              <input
                type="checkbox"
                checked={chosen.includes(project.key)}
                onChange={(event) => toggle(project.key, event.target.checked)}
              />
              <span className="min-w-0 wrap-anywhere text-body">
                <span className="font-mono">{project.key}</span>
                {project.title === '' ? null : (
                  <span className="text-muted"> — {project.title}</span>
                )}
              </span>
            </label>
          ))}
          {mode === 'only' && chosen.length === 0 ? (
            <p className="text-meta text-muted">{t('projects.onlyEmpty')}</p>
          ) : null}
        </fieldset>
      ) : null}

      <p className="max-w-(--ui-text-max) text-meta text-muted">{t('projects.scope')}</p>

      {/* Кнопка выше всего изменчивого: отказ, выросший над ней, увёл бы её из-под
          пальца (`TRK/ui-screens#21`). */}
      <div className="flex flex-wrap gap-2">
        <Button type="submit" disabled={save.isPending}>
          {save.isPending ? t('projects.pending') : t('projects.save')}
        </Button>
        <Button tone="quiet" onClick={onClose}>
          {t('cancel')}
        </Button>
      </div>

      {save.error === null || save.error === undefined ? null : (
        <Callout tone="danger">
          {ownedByAnother ? t('projects.ownedByAnother') : errorMessage(save.error)}
        </Callout>
      )}
    </form>
  );
}
