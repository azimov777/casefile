import { useId, useState, type FormEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { Signpost } from 'lucide-react';
import { areasQueryOptions, type TaskArea } from '@/entities/area';
import { errorMessage } from '@/shared/errors';
import { Button, Callout, Dialog, QueryState } from '@/shared/ui';
import { useChangeTaskArea } from '../model/use-change-area';

/** Значение переключателя «без области»: адреса без косой черты не бывает. */
const NONE = '';

interface ChangeTaskAreaProps {
  taskKey: string;
  projectKey: string;
  /** Нынешняя область задачи из пакета карточки; `null` — без области. */
  current: TaskArea | null;
}

/**
 * Кнопка «Изменить» у области в полосе свойств карточки и её окно: выбрать
 * область проекта или «без области» (TRK-557, TRK#16, ч. 4: «поле правится там
 * же, где приоритет»).
 *
 * Выбор — переключатели, а не выпадающий список: областей у проекта единицы, и каждая
 * видна сразу с описанием, — выбирают по смыслу, а не по ключу. Предлагаются только
 * активные: архивная область бэкенд не поставит (`area_archived`). Нынешняя
 * архивная стоит среди вариантов, чтобы окно открывалось на правде, а уйти из неё можно
 * одним выбором «без области» — снять область можно всегда.
 *
 * Показывать кнопку или нет, решает место вызова: у закрытой задачи и у задачи
 * архивного проекта правки нет вовсе (`task_closed`, `project_archived`).
 */
export function ChangeTaskArea({ taskKey, projectKey, current }: ChangeTaskAreaProps) {
  const [open, setOpen] = useState(false);
  const { t } = useTranslation('area');

  return (
    <Dialog
      open={open}
      onOpenChange={setOpen}
      title={t('task.title', { key: taskKey })}
      description={t('task.intro')}
      closeLabel={t('close')}
      trigger={
        <Button tone="quiet" size="sm" aria-label={t('task.label', { key: taskKey })}>
          <Signpost className="size-(--ui-mark)" aria-hidden="true" />
          {t('task.open')}
        </Button>
      }
    >
      <ChangeAreaForm
        taskKey={taskKey}
        projectKey={projectKey}
        current={current}
        onDone={() => setOpen(false)}
      />
    </Dialog>
  );
}

/** Форма окна: рождается заново при каждом открытии и начинает с нынешнего значения. */
function ChangeAreaForm({
  taskKey,
  projectKey,
  current,
  onDone,
}: ChangeTaskAreaProps & { onDone: () => void }) {
  const areas = useQuery(areasQueryOptions(projectKey));
  const change = useChangeTaskArea();
  const [chosen, setChosen] = useState(current?.address ?? NONE);
  const legendId = useId();
  const { t } = useTranslation('area');

  const active = areas.data?.items ?? [];
  // Нынешнее архивное в списке активных не придёт — оно стоит отдельной строкой.
  const currentArchived =
    current !== null && !active.some((item) => item.address === current.address) ? current : null;
  const unchanged = chosen === (current?.address ?? NONE);

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (unchanged) {
      onDone();
      return;
    }
    change.mutate({ taskKey, area: chosen === NONE ? null : chosen }, { onSuccess: onDone });
  }

  return (
    <form className="flex flex-col gap-4" onSubmit={submit} noValidate>
      {areas.data === undefined ? (
        <QueryState query={areas} loading={t('task.loading')} />
      ) : (
        <div
          role="radiogroup"
          aria-labelledby={legendId}
          className="flex max-h-80 flex-col gap-1 overflow-y-auto"
        >
          <span className="text-meta text-muted" id={legendId}>
            {t('task.legend')}
          </span>
          <Choice
            name={legendId}
            value={NONE}
            chosen={chosen}
            onChoose={setChosen}
            title={t('task.none')}
            hint={t('task.noneHint')}
          />
          {currentArchived === null ? null : (
            <Choice
              name={legendId}
              value={currentArchived.address}
              chosen={chosen}
              onChoose={setChosen}
              title={t('task.archivedOption', { title: currentArchived.title })}
              address={currentArchived.address}
              hint={t('task.archivedHint')}
            />
          )}
          {active.map((item) => (
            <Choice
              key={item.address}
              name={legendId}
              value={item.address}
              chosen={chosen}
              onChoose={setChosen}
              title={item.title}
              address={item.address}
              hint={item.description}
            />
          ))}
          {active.length === 0 ? (
            <p className="text-meta text-muted italic">{t('task.noAreas')}</p>
          ) : null}
        </div>
      )}

      <div className="flex flex-wrap gap-2">
        {/* Пока области читаются, выбор стоит на нынешнем значении, и «Сохранить»
            закрывает окно без запроса: кнопку незачем запирать и отпирать через кадр. */}
        <Button type="submit" disabled={change.isPending}>
          {change.isPending ? t('task.pending') : t('task.submit')}
        </Button>
        <Button tone="quiet" onClick={onDone}>
          {t('cancel')}
        </Button>
      </div>

      {change.isError ? <Callout tone="danger">{errorMessage(change.error)}</Callout> : null}
    </form>
  );
}

/** Один вариант: переключатель, название, адрес моноширинным и описание мельче. */
function Choice({
  name,
  value,
  chosen,
  onChoose,
  title,
  address,
  hint,
}: {
  name: string;
  value: string;
  chosen: string;
  onChoose: (value: string) => void;
  title: string;
  address?: string;
  hint?: string;
}) {
  return (
    <label className="flex cursor-pointer items-start gap-2 rounded-control px-2 py-1.5 hover:bg-sunken has-checked:bg-accent-soft">
      <input
        type="radio"
        name={name}
        value={value}
        checked={chosen === value}
        onChange={() => onChoose(value)}
        className="mt-1 size-(--ui-mark) shrink-0 accent-accent"
      />
      <span className="flex min-w-0 flex-col">
        <span className="flex flex-wrap items-baseline gap-x-2">
          <span className="wrap-anywhere">{title}</span>
          {address === undefined ? null : (
            <span className="font-mono text-meta text-muted">{address}</span>
          )}
        </span>
        {hint === undefined || hint.trim() === '' ? null : (
          <span className="text-meta text-muted wrap-anywhere">{hint}</span>
        )}
      </span>
    </label>
  );
}
