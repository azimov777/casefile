import { useId, useState, type FormEvent, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { complainsAbout, errorMessage } from '@/shared/errors';
import { Button, Callout, Dialog, Input } from '@/shared/ui';
import { useRegisterAgent } from '../model/use-access-actions';

/**
 * Окно «Завести агента»: новый участник реестра, чьим именем будут подписаны его
 * записи в делах.
 *
 * Токена участнику это не даёт: доступ выпускается отдельным действием, и окно прямо
 * об этом говорит, предлагая перейти к выпуску сразу. Без этого человек заводил бы
 * участника и уходил с экрана, считая агента подключённым.
 *
 * Имя проверяет бэкенд, а не форма: шаблон имени — правило предметной области
 * (`app/domain/participants.py`), и вторая его копия на клиенте разошлась бы с первой
 * молча. Форма объясняет отказ, а не предвосхищает его.
 *
 * Кнопка, которая открывает окно, приходит пропсом `trigger` (`shared/ui/dialog.tsx`,
 * `UI-175`) и держится смонтированной постоянно — сама страница называет её, `open`
 * лишь решает, видно ли содержимое. Без `trigger` Radix после `Esc` и «Закрыть» не
 * находит, кому вернуть фокус, и он падает на `body` (`UI-175#11`, `UI-178`).
 *
 * `registered` — единственная часть состояния, что живёт здесь, а не в форме: от него
 * зависит подпись окна (`description`), которую держит `Dialog`, а не `children`.
 * Остальное поле формы рождается заново при каждом открытии (`AgentForm` ниже, как
 * часть `children` — Radix монтирует их только пока окно открыто), и `registered`
 * обнуляется тем же путём: закрытие всегда возвращает окно к чистому состоянию.
 */
export function AgentDialog({
  open,
  onOpenChange,
  trigger,
  onIssueFor,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  trigger: ReactNode;
  /** Перейти к выпуску токена этому участнику. */
  onIssueFor: (participant: string) => void;
}) {
  const [registered, setRegistered] = useState<string | null>(null);
  const { t } = useTranslation('access');

  function handleOpenChange(next: boolean) {
    onOpenChange(next);
    if (!next) setRegistered(null);
  }

  function close() {
    handleOpenChange(false);
  }

  return (
    <Dialog
      open={open}
      onOpenChange={handleOpenChange}
      trigger={trigger}
      title={t('agent.title')}
      description={registered === null ? t('agent.intro') : t('agent.doneIntro')}
      closeLabel={t('close')}
    >
      {registered === null ? (
        <AgentForm onRegistered={setRegistered} onClose={close} />
      ) : (
        <div className="flex flex-col gap-4">
          <p className="max-w-(--ui-text-max) text-body">{t('agent.done', { name: registered })}</p>
          <div className="flex flex-wrap gap-2">
            <Button
              onClick={() => {
                close();
                onIssueFor(registered);
              }}
            >
              {t('agent.issueNow')}
            </Button>
            <Button tone="quiet" onClick={close}>
              {t('close')}
            </Button>
          </div>
        </div>
      )}
    </Dialog>
  );
}

/** Форма заведения: имя и описание. Живёт в `children` окна и рождается заново на каждый заход. */
function AgentForm({
  onRegistered,
  onClose,
}: {
  onRegistered: (name: string) => void;
  onClose: () => void;
}) {
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const register = useRegisterAgent();
  const nameId = useId();
  const nameHintId = useId();
  const descriptionId = useId();
  const { t } = useTranslation('access');

  const failed = register.error !== null && register.error !== undefined;
  const badName = complainsAbout(register.error, 'name');

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (name.trim() === '') return;

    register.mutate(
      { name: name.trim(), description: description.trim() },
      { onSuccess: (participant) => onRegistered(participant.name) },
    );
  }

  return (
    <form className="flex flex-col gap-4" onSubmit={submit} noValidate>
      <div className="flex flex-col gap-1">
        <label className="text-meta text-muted" htmlFor={nameId}>
          {t('agent.nameLabel')}
        </label>
        <Input
          id={nameId}
          className="font-mono"
          value={name}
          onChange={(event) => setName(event.target.value)}
          autoComplete="off"
          spellCheck={false}
          aria-invalid={badName}
          aria-describedby={nameHintId}
          placeholder={t('agent.namePlaceholder')}
        />
        <span className="text-meta text-muted" id={nameHintId}>
          {t('agent.nameHint')}
        </span>
      </div>

      <div className="flex flex-col gap-1">
        <label className="text-meta text-muted" htmlFor={descriptionId}>
          {t('agent.descriptionLabel')}
        </label>
        <Input
          id={descriptionId}
          value={description}
          onChange={(event) => setDescription(event.target.value)}
          placeholder={t('agent.descriptionPlaceholder')}
        />
      </div>

      {/* Кнопка выше всего изменчивого: отказ, выросший над ней, увёл бы её
          из-под пальца (`docs/notes/ui.md`). */}
      <div className="flex flex-wrap gap-2">
        <Button type="submit" disabled={register.isPending || name.trim() === ''}>
          {register.isPending ? t('agent.pending') : t('agent.submit')}
        </Button>
        <Button tone="quiet" onClick={onClose}>
          {t('cancel')}
        </Button>
      </div>

      {failed ? (
        <Callout tone="danger">
          {errorMessage(register.error)} {badName ? t('agent.nameRule') : null}
        </Callout>
      ) : null}
    </form>
  );
}
