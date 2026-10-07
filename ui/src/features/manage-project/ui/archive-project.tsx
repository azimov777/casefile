import { useState, type FormEvent, type RefObject } from 'react';
import { useTranslation } from 'react-i18next';
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
 * Открывать окно или нет, решает место вызова — по `archived_at` из контракта: окно само
 * не знает ни прав, ни состояния проекта.
 */

type Area = 'archive' | 'restore';

/**
 * Окно «В архив» у активного проекта и «Восстановить» у архивного — одно окно, чей
 * вопрос следует за `archived_at`. Своей кнопки у окна нет: его открывает пункт меню «⋯»
 * в шапке экрана (`ProjectMenu`, TRK-618), и после закрытия фокус возвращается на «⋯»
 * (`returnFocus`) — кнопку, которая переживает и архив, и восстановление: перечитанная
 * карточка меняет пункты меню, а не саму кнопку, и человек с клавиатуры не начинает
 * страницу сначала.
 *
 * Архив спрашивает ролью `alertdialog`: он замораживает проект и все его задачи — агенты
 * получат отказ на любое изменение, — и окно спрашивает об этом до, а не после.
 */
export function ProjectArchiving({
  projectKey,
  archived,
  open,
  onOpenChange,
  returnFocus,
}: {
  projectKey: string;
  archived: boolean;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  returnFocus: RefObject<HTMLElement | null>;
}) {
  const area: Area = archived ? 'restore' : 'archive';
  const { t } = useTranslation('project');

  return (
    <Dialog
      alert={area === 'archive'}
      open={open}
      onOpenChange={onOpenChange}
      title={t(`${area}.title`, { key: projectKey })}
      description={t(`${area}.intro`)}
      closeLabel={t('close')}
      returnFocus={returnFocus}
    >
      <ArchivingForm projectKey={projectKey} area={area} onDone={() => onOpenChange(false)} />
    </Dialog>
  );
}

/**
 * Форма окна. Живёт внутри содержимого окна и рождается заново при каждом открытии:
 * прошлый отказ и прошлая причина в новое окно не переезжают.
 */
function ArchivingForm({
  projectKey,
  area,
  onDone,
}: {
  projectKey: string;
  area: Area;
  onDone: () => void;
}) {
  const [reason, setReason] = useState('');
  const [emptyReason, setEmptyReason] = useState(false);
  const archive = useArchiveProject();
  const restore = useRestoreProject();
  const action = area === 'archive' ? archive : restore;
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
        label={t(`${area}.reasonLabel`)}
        value={reason}
        onChange={(next) => {
          setReason(next);
          if (next.trim() !== '') setEmptyReason(false);
        }}
        hint={t(`${area}.reasonHint`)}
        problem={emptyReason ? t(`${area}.reasonEmpty`) : null}
      />

      <div className="flex flex-wrap gap-2">
        <Button type="submit" disabled={action.isPending}>
          {action.isPending ? t(`${area}.pending`) : t(`${area}.submit`)}
        </Button>
        <Button tone="quiet" onClick={onDone}>
          {t('cancel')}
        </Button>
      </div>

      {action.isError ? <Callout tone="danger">{errorMessage(action.error)}</Callout> : null}
    </form>
  );
}
