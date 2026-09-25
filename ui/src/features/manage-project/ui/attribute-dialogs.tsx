import { useId, useState, type FormEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { Plus } from 'lucide-react';
import type { ProjectAttribute } from '@/entities/project';
import { ApiError } from '@/shared/api';
import { complainsAbout, errorMessage } from '@/shared/errors';
import { Button, Callout, Dialog, Input, Textarea } from '@/shared/ui';
import { useRemoveAttribute, useSetAttribute } from '../model/use-project-actions';
import { ReasonField } from './reason-field';

/*
 * Окна атрибута (`UI-175`, решение 4 `TRK-150`): заведение — без причины, изменение и
 * снятие — с причиной, и причина здесь обязательное поле, а не необязательная строка.
 * Без неё окно не отправляет запрос вовсе и говорит почему: история атрибута существует
 * ради ответа «почему прежнее значение перестало быть верным».
 *
 * Имя и значение проверяет бэкенд (`invalid_attribute_name`,
 * `attribute_value_too_long`): образцы — правило предметной области, и вторая их копия
 * здесь разошлась бы с первой молча. Окно называет образец подсказкой и объясняет отказ.
 */

/** Кнопка «Добавить атрибут» и окно заведения: имя и значение. */
export function AddAttribute({ projectKey }: { projectKey: string }) {
  const [open, setOpen] = useState(false);
  const { t } = useTranslation('project');

  return (
    <Dialog
      open={open}
      onOpenChange={setOpen}
      title={t('attribute.addTitle')}
      description={t('attribute.addIntro')}
      closeLabel={t('close')}
      trigger={
        <Button tone="quiet" size="sm">
          <Plus className="size-(--ui-mark)" aria-hidden="true" />
          {t('attribute.add')}
        </Button>
      }
    >
      <AddAttributeForm projectKey={projectKey} onDone={() => setOpen(false)} />
    </Dialog>
  );
}

function AddAttributeForm({ projectKey, onDone }: { projectKey: string; onDone: () => void }) {
  const [name, setName] = useState('');
  const [value, setValue] = useState('');
  const [emptyName, setEmptyName] = useState(false);
  const set = useSetAttribute();
  const nameId = useId();
  const nameHintId = useId();
  const { t } = useTranslation('project');

  const badName = errorCode(set.error) === 'invalid_attribute_name';

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (name.trim() === '') {
      setEmptyName(true);
      return;
    }
    set.mutate({ projectKey, name: name.trim(), value, reason: null }, { onSuccess: onDone });
  }

  return (
    <form className="flex flex-col gap-4" onSubmit={submit} noValidate>
      <div className="flex flex-col gap-1">
        <label className="text-meta text-muted" htmlFor={nameId}>
          {t('attribute.nameLabel')}
        </label>
        <Input
          id={nameId}
          className="font-mono"
          value={name}
          onChange={(event) => {
            setName(event.target.value);
            setEmptyName(false);
          }}
          autoComplete="off"
          autoCapitalize="off"
          spellCheck={false}
          aria-invalid={emptyName || badName}
          aria-describedby={nameHintId}
        />
        <span className="text-meta text-muted" id={nameHintId}>
          {t('attribute.nameHint')}
        </span>
        {emptyName ? (
          <span className="text-meta text-danger" role="alert">
            {t('attribute.nameEmpty')}
          </span>
        ) : null}
      </div>

      <ValueField value={value} onChange={setValue} invalid={isValueProblem(set.error)} />

      <div className="flex flex-wrap gap-2">
        <Button type="submit" disabled={set.isPending}>
          {set.isPending ? t('attribute.pending') : t('attribute.addSubmit')}
        </Button>
        <Button tone="quiet" onClick={onDone}>
          {t('cancel')}
        </Button>
      </div>

      {set.isError ? (
        <Callout tone="danger">
          {errorMessage(set.error)} {badName ? t('attribute.nameHint') : t('retrySafe')}
        </Callout>
      ) : null}
    </form>
  );
}

/** Кнопка «Изменить» у строки атрибута и окно: новое значение и причина. */
export function ChangeAttribute({
  projectKey,
  attribute,
}: {
  projectKey: string;
  attribute: ProjectAttribute;
}) {
  const [open, setOpen] = useState(false);
  const { t } = useTranslation('project');

  return (
    <Dialog
      open={open}
      onOpenChange={setOpen}
      title={t('attribute.changeTitle', { name: attribute.name })}
      description={t('attribute.changeIntro')}
      closeLabel={t('close')}
      trigger={
        // Имя кнопки начинается с её видимой подписи: голосовой ввод находит кнопку
        // по тому, что человек видит, а диктор называет, чей это атрибут.
        <Button
          tone="quiet"
          size="sm"
          aria-label={t('attribute.changeLabel', { name: attribute.name })}
        >
          {t('attribute.change')}
        </Button>
      }
    >
      <ChangeAttributeForm
        projectKey={projectKey}
        attribute={attribute}
        onDone={() => setOpen(false)}
      />
    </Dialog>
  );
}

function ChangeAttributeForm({
  projectKey,
  attribute,
  onDone,
}: {
  projectKey: string;
  attribute: ProjectAttribute;
  onDone: () => void;
}) {
  const [value, setValue] = useState(attribute.value);
  const [reason, setReason] = useState('');
  const [emptyReason, setEmptyReason] = useState(false);
  const set = useSetAttribute();
  const { t } = useTranslation('project');

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (reason.trim() === '') {
      setEmptyReason(true);
      return;
    }
    set.mutate(
      { projectKey, name: attribute.name, value, reason: reason.trim() },
      { onSuccess: onDone },
    );
  }

  return (
    <form className="flex flex-col gap-4" onSubmit={submit} noValidate>
      <ValueField value={value} onChange={setValue} invalid={isValueProblem(set.error)} />
      <ReasonField
        label={t('attribute.reasonLabel')}
        value={reason}
        onChange={(next) => {
          setReason(next);
          if (next.trim() !== '') setEmptyReason(false);
        }}
        hint={t('attribute.reasonHint')}
        problem={emptyReason ? t('attribute.reasonEmpty') : null}
      />

      <div className="flex flex-wrap gap-2">
        <Button type="submit" disabled={set.isPending}>
          {set.isPending ? t('attribute.pending') : t('attribute.changeSubmit')}
        </Button>
        <Button tone="quiet" onClick={onDone}>
          {t('cancel')}
        </Button>
      </div>

      {set.isError ? (
        <Callout tone="danger">
          {errorMessage(set.error)} {t('retrySafe')}
        </Callout>
      ) : null}
    </form>
  );
}

/**
 * Кнопка «Снять» у строки атрибута и окно подтверждения с причиной. Роль
 * `alertdialog`: снятие убирает факт из карточки, и окно спрашивает о нём до, а не
 * после.
 */
export function RemoveAttribute({
  projectKey,
  attribute,
}: {
  projectKey: string;
  attribute: ProjectAttribute;
}) {
  const [open, setOpen] = useState(false);
  const { t } = useTranslation('project');

  return (
    <Dialog
      alert
      open={open}
      onOpenChange={setOpen}
      title={t('attribute.removeTitle', { name: attribute.name })}
      description={t('attribute.removeIntro')}
      closeLabel={t('close')}
      trigger={
        <Button
          tone="quiet"
          size="sm"
          aria-label={t('attribute.removeLabel', { name: attribute.name })}
        >
          {t('attribute.remove')}
        </Button>
      }
    >
      <RemoveAttributeForm
        projectKey={projectKey}
        attribute={attribute}
        onDone={() => setOpen(false)}
      />
    </Dialog>
  );
}

function RemoveAttributeForm({
  projectKey,
  attribute,
  onDone,
}: {
  projectKey: string;
  attribute: ProjectAttribute;
  onDone: () => void;
}) {
  const [reason, setReason] = useState('');
  const [emptyReason, setEmptyReason] = useState(false);
  const remove = useRemoveAttribute();
  const { t } = useTranslation('project');

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (reason.trim() === '') {
      setEmptyReason(true);
      return;
    }
    remove.mutate(
      { projectKey, name: attribute.name, reason: reason.trim() },
      { onSuccess: onDone },
    );
  }

  return (
    <form className="flex flex-col gap-4" onSubmit={submit} noValidate>
      <ReasonField
        label={t('attribute.reasonLabel')}
        value={reason}
        onChange={(next) => {
          setReason(next);
          if (next.trim() !== '') setEmptyReason(false);
        }}
        hint={t('attribute.removeReasonHint')}
        problem={emptyReason ? t('attribute.removeReasonEmpty') : null}
      />

      <div className="flex flex-wrap gap-2">
        <Button type="submit" disabled={remove.isPending}>
          {remove.isPending ? t('attribute.removePending') : t('attribute.removeSubmit')}
        </Button>
        <Button tone="quiet" onClick={onDone}>
          {t('cancel')}
        </Button>
      </div>

      {remove.isError ? (
        <Callout tone="danger">
          {errorMessage(remove.error)} {t('retrySafe')}
        </Callout>
      ) : null}
    </form>
  );
}

/** Значение атрибута: простой текст в несколько строк, хранится как набран. */
function ValueField({
  value,
  onChange,
  invalid,
}: {
  value: string;
  onChange: (value: string) => void;
  invalid: boolean;
}) {
  const id = useId();
  const hintId = useId();
  const { t } = useTranslation('project');

  return (
    <div className="flex flex-col gap-1">
      <label className="text-meta text-muted" htmlFor={id}>
        {t('attribute.valueLabel')}
      </label>
      <Textarea
        id={id}
        rows={2}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        aria-invalid={invalid}
        aria-describedby={hintId}
      />
      <span className="text-meta text-muted" id={hintId}>
        {t('attribute.valueHint')}
      </span>
    </div>
  );
}

/** Жалоба на значение: слишком длинное или схема не приняла поле `value`. */
function isValueProblem(error: unknown): boolean {
  return errorCode(error) === 'attribute_value_too_long' || complainsAbout(error, 'value');
}

function errorCode(error: unknown): string | null {
  return error instanceof ApiError ? error.code : null;
}
