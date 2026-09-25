import { useState, type FormEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { Archive, ArchiveRestore } from 'lucide-react';
import { errorMessage } from '@/shared/errors';
import { Button, Callout, Dialog } from '@/shared/ui';
import { useArchiveProject, useRestoreProject } from '../model/use-project-actions';
import { ReasonField } from './reason-field';

/*
 * Архив и восстановление проекта (`UI-176`, решение 6 `TRK-150`): оба — с обязательной
 * причиной, как изменение и снятие атрибута. Без причины окно не отправляет запрос вовсе
 * и говорит почему: причина уезжает в запись `archived` или `restored` дела проекта, и
 * это единственный след того, зачем проект замораживали.
 *
 * Показывать кнопку или нет, решает место вызова — по набору ключа (`main`) и по
 * `archived_at` из контракта: окно само не знает ни прав, ни состояния проекта.
 */

type Direction = 'archive' | 'restore';

/**
 * Кнопка «В архив» у активного проекта и «Восстановить» у архивного — одна кнопка, чья
 * подпись следует за `archived_at`. Одна, а не две в разных местах: после удачного
 * архива окно закрывается, фокус возвращается на кнопку, и только потом перечитанная
 * карточка меняет её подпись. Будь это две кнопки, первая исчезла бы вместе с фокусом, и
 * человек с клавиатуры начинал бы страницу сначала.
 *
 * Архив спрашивает ролью `alertdialog`: он замораживает проект и все его задачи — агенты
 * получат отказ на любое изменение, — и окно спрашивает об этом до, а не после.
 */
export function ProjectArchiving({
  projectKey,
  archived,
}: {
  projectKey: string;
  archived: boolean;
}) {
  const direction: Direction = archived ? 'restore' : 'archive';
  const [open, setOpen] = useState(false);
  const { t } = useTranslation('project');
  const Icon = direction === 'archive' ? Archive : ArchiveRestore;

  return (
    <Dialog
      alert={direction === 'archive'}
      open={open}
      onOpenChange={setOpen}
      title={t(`${direction}.title`, { key: projectKey })}
      description={t(`${direction}.intro`)}
      closeLabel={t('close')}
      trigger={
        <Button tone="quiet" size="sm">
          <Icon className="size-(--ui-mark)" aria-hidden="true" />
          {t(`${direction}.open`)}
        </Button>
      }
    >
      <ArchivingForm projectKey={projectKey} direction={direction} onDone={() => setOpen(false)} />
    </Dialog>
  );
}

/**
 * Форма окна. Живёт внутри содержимого окна и рождается заново при каждом открытии:
 * прошлый отказ и прошлая причина в новое окно не переезжают.
 */
function ArchivingForm({
  projectKey,
  direction,
  onDone,
}: {
  projectKey: string;
  direction: Direction;
  onDone: () => void;
}) {
  const [reason, setReason] = useState('');
  const [emptyReason, setEmptyReason] = useState(false);
  const archive = useArchiveProject();
  const restore = useRestoreProject();
  const action = direction === 'archive' ? archive : restore;
  const { t } = useTranslation('project');

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (reason.trim() === '') {
      setEmptyReason(true);
      return;
    }
    action.mutate({ key: projectKey, reason: reason.trim() }, { onSuccess: onDone });
  }

  return (
    <form className="flex flex-col gap-4" onSubmit={submit} noValidate>
      <ReasonField
        label={t(`${direction}.reasonLabel`)}
        value={reason}
        onChange={(next) => {
          setReason(next);
          if (next.trim() !== '') setEmptyReason(false);
        }}
        hint={t(`${direction}.reasonHint`)}
        problem={emptyReason ? t(`${direction}.reasonEmpty`) : null}
      />

      <div className="flex flex-wrap gap-2">
        <Button type="submit" disabled={action.isPending}>
          {action.isPending ? t(`${direction}.pending`) : t(`${direction}.submit`)}
        </Button>
        <Button tone="quiet" onClick={onDone}>
          {t('cancel')}
        </Button>
      </div>

      {action.isError ? <Callout tone="danger">{errorMessage(action.error)}</Callout> : null}
    </form>
  );
}
