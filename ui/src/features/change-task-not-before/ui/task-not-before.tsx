import { useState, type FormEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { CalendarClock } from 'lucide-react';
import { DeferredMark } from '@/entities/task';
import { useLanguage } from '@/shared/i18n';
import { errorMessage } from '@/shared/errors';
import { momentLabel } from '@/shared/lib';
import { Button, Callout, Dialog, Input } from '@/shared/ui';
import { fromLocalInput, toLocalInput } from '../model/local-moment';
import { useChangeTaskNotBefore } from '../model/use-change-not-before';

interface TaskNotBeforeProps {
  taskKey: string;
  /** Момент из карточки; `null` — не отложена. */
  notBefore: string | null;
  /** Признак сервера: момент ещё впереди по часам базы. Часы браузера в этом не участвуют. */
  deferred: boolean;
  /** Правка доступна: сеанс известен, задача не закрыта, проект не в архиве. */
  canChange: boolean;
}

/**
 * Момент «можно взять с …» в полосе свойств карточки (TRK-593, TRK#47, п. 6): строка с
 * моментом в поясе браузера, значок отложенной задачи, пока она отложена по часам базы, и
 * кнопки «Изменить»/«Снять» или «Отложить…». У закрытой задачи — только строка.
 *
 * Это не срок: ни отсчёта, ни тревожного цвета. Прошедший момент показан строкой без значка.
 */
export function TaskNotBefore({ taskKey, notBefore, deferred, canChange }: TaskNotBeforeProps) {
  const { t } = useTranslation('task');
  const { language } = useLanguage();
  const clear = useChangeTaskNotBefore();

  return (
    <div className="flex flex-col gap-1">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        {notBefore === null ? (
          <span className="text-muted italic">{t('notBefore.none')}</span>
        ) : (
          <>
            {deferred ? <DeferredMark notBefore={notBefore} pressable /> : null}
            <span data-not-before={notBefore}>
              {t('notBefore.line', { moment: momentLabel(notBefore, language, { month: 'long' }) })}
            </span>
          </>
        )}
        {canChange ? (
          <>
            <NotBeforeDialog
              taskKey={taskKey}
              notBefore={notBefore}
              label={t(notBefore === null ? 'notBefore.deferLabel' : 'notBefore.changeLabel', {
                key: taskKey,
              })}
              open={t(notBefore === null ? 'notBefore.defer' : 'notBefore.change')}
            />
            {notBefore === null ? null : (
              <Button
                tone="quiet"
                size="sm"
                disabled={clear.isPending}
                aria-label={t('notBefore.clearLabel', { key: taskKey })}
                onClick={() => clear.mutate({ taskKey, notBefore: null })}
              >
                {t('notBefore.clear')}
              </Button>
            )}
          </>
        ) : null}
      </div>
      {clear.isError ? <Callout tone="danger">{errorMessage(clear.error)}</Callout> : null}
    </div>
  );
}

function NotBeforeDialog({
  taskKey,
  notBefore,
  label,
  open: openLabel,
}: {
  taskKey: string;
  notBefore: string | null;
  label: string;
  open: string;
}) {
  const [open, setOpen] = useState(false);
  const { t } = useTranslation('task');

  return (
    <Dialog
      open={open}
      onOpenChange={setOpen}
      title={t('notBefore.title', { key: taskKey })}
      description={t('notBefore.intro')}
      closeLabel={t('notBefore.close')}
      trigger={
        <Button tone="quiet" size="sm" aria-label={label}>
          <CalendarClock className="size-(--ui-mark)" aria-hidden="true" />
          {openLabel}
        </Button>
      }
    >
      <NotBeforeForm taskKey={taskKey} notBefore={notBefore} onDone={() => setOpen(false)} />
    </Dialog>
  );
}

/** Форма окна: рождается заново при каждом открытии и начинает с нынешнего момента. */
function NotBeforeForm({
  taskKey,
  notBefore,
  onDone,
}: {
  taskKey: string;
  notBefore: string | null;
  onDone: () => void;
}) {
  const { t } = useTranslation('task');
  const change = useChangeTaskNotBefore();
  const [value, setValue] = useState(toLocalInput(notBefore));
  const [empty, setEmpty] = useState(false);
  const inputId = `not-before-${taskKey}`;

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const moment = fromLocalInput(value);
    if (moment === null) {
      setEmpty(true);
      return;
    }
    setEmpty(false);
    change.mutate({ taskKey, notBefore: moment }, { onSuccess: onDone });
  }

  return (
    <form className="flex flex-col gap-4" onSubmit={submit} noValidate>
      <div className="flex flex-col gap-1">
        <label htmlFor={inputId} className="text-meta text-muted">
          {t('notBefore.inputLabel')}
        </label>
        <Input
          id={inputId}
          type="datetime-local"
          value={value}
          aria-invalid={empty || change.isError}
          aria-describedby={`${inputId}-hint`}
          onChange={(event) => {
            setValue(event.target.value);
            setEmpty(false);
          }}
        />
        <p id={`${inputId}-hint`} className="text-meta text-muted">
          {empty ? t('notBefore.empty') : t('notBefore.inputHint')}
        </p>
      </div>

      <div className="flex flex-wrap gap-2">
        <Button type="submit" disabled={change.isPending}>
          {change.isPending ? t('notBefore.pending') : t('notBefore.submit')}
        </Button>
        <Button tone="quiet" onClick={onDone}>
          {t('notBefore.cancel')}
        </Button>
      </div>

      {change.isError ? <Callout tone="danger">{errorMessage(change.error)}</Callout> : null}
    </form>
  );
}
