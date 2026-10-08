import { useId, useState, type FormEvent, type ReactNode, type RefObject } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router';
import { Archive, ArchiveRestore, Pencil, Plus } from 'lucide-react';
import { AREA_DESCRIPTION_LIMIT } from '@/entities/area';
import { descriptionLength } from '@/entities/project';
import { ApiError } from '@/shared/api';
import { complainsAbout, errorMessage } from '@/shared/errors';
import { areaHref } from '@/shared/lib';
import { Button, Callout, Dialog, Input } from '@/shared/ui';
import {
  useArchiveArea,
  useCreateArea,
  useRestoreArea,
  useUpdateArea,
} from '../model/use-project-actions';
import { DescriptionField } from './description-field';
import { ReasonField } from './reason-field';

/*
 * Окна области (TRK-557, TRK#57): завести, править название и
 * описание, архивировать и восстановить с причиной. Правила те же, что у проекта
 * (`UI-175`, `UI-176`): ключ неизменяем и потому есть только у заведения, причина архива
 * обязательна, образец ключа и занятость проверяет бэкенд. Показывать кнопки или нет,
 * решает место вызова — по `useProjectRights` и по `archived_at` из контракта.
 */

/** Отказы, чья причина — сам набранный ключ: их текст стоит у поля ключа. */
const KEY_REFUSALS: readonly string[] = ['area_key_taken', 'invalid_area_key'];

/** Длиннее ли описание области предела: тогда окно не отправляет его вовсе. */
function tooLongDescription(description: string): boolean {
  return descriptionLength(description) > AREA_DESCRIPTION_LIMIT;
}

/**
 * Кнопка «Новая область» в разделе «Области» проекта и её окно: ключ, название,
 * описание. Заведённая область открывается сразу, как заведённый проект: её заводят,
 * чтобы вести, и первым делом нужна её страница.
 */
export function CreateArea({ projectKey }: { projectKey: string }) {
  const [open, setOpen] = useState(false);
  const navigate = useNavigate();
  const { t } = useTranslation('area');

  return (
    <Dialog
      open={open}
      onOpenChange={setOpen}
      title={t('create.title', { key: projectKey })}
      description={t('create.intro')}
      closeLabel={t('close')}
      trigger={
        <Button tone="quiet" size="sm">
          <Plus className="size-(--ui-mark)" aria-hidden="true" />
          {t('create.open')}
        </Button>
      }
    >
      <CreateAreaForm
        projectKey={projectKey}
        onCancel={() => setOpen(false)}
        onCreated={(address) => {
          setOpen(false);
          void navigate(areaHref(address));
        }}
      />
    </Dialog>
  );
}

/** Форма окна: рождается заново при каждом открытии, прошлый отказ в неё не переезжает. */
function CreateAreaForm({
  projectKey,
  onCancel,
  onCreated,
}: {
  projectKey: string;
  onCancel: () => void;
  onCreated: (address: string) => void;
}) {
  const [key, setKey] = useState('');
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [problem, setProblem] = useState<'key' | 'title' | null>(null);
  const create = useCreateArea();
  const keyId = useId();
  const keyHintId = useId();
  const keyRefusedId = useId();
  const titleId = useId();
  const { t } = useTranslation('area');

  const keyRefused =
    create.error instanceof ApiError && KEY_REFUSALS.includes(create.error.code)
      ? errorMessage(create.error)
      : null;
  const badKey = complainsAbout(create.error, 'key') || keyRefused !== null;
  const badTitle = complainsAbout(create.error, 'title');
  const tooLong = tooLongDescription(description);

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (key.trim() === '') {
      setProblem('key');
      return;
    }
    if (title.trim() === '') {
      setProblem('title');
      return;
    }
    if (tooLong) return;
    setProblem(null);

    create.mutate(
      { projectKey, key: key.trim(), title: title.trim(), description: description.trim() },
      { onSuccess: (area) => onCreated(area.address) },
    );
  }

  return (
    <form className="flex flex-col gap-4" onSubmit={submit} noValidate>
      <div className="flex flex-col gap-1">
        <label className="text-meta text-muted" htmlFor={keyId}>
          {t('create.keyLabel')}
        </label>
        {/* Ключ — часть адреса `TRK/promotion`: моноширинным, без автоподстановок
            клавиатуры телефона. Образец назван подсказкой, а проверяет его бэкенд. */}
        <Input
          id={keyId}
          className="font-mono"
          value={key}
          onChange={(event) => {
            setKey(event.target.value);
            setProblem(null);
          }}
          autoComplete="off"
          autoCapitalize="none"
          spellCheck={false}
          aria-invalid={problem === 'key' || badKey}
          aria-describedby={keyRefused === null ? keyHintId : `${keyHintId} ${keyRefusedId}`}
        />
        <span className="text-meta text-muted" id={keyHintId}>
          {t('create.keyHint', { key: projectKey })}
        </span>
        {problem === 'key' ? (
          <span className="text-meta text-danger" role="alert">
            {t('create.keyEmpty')}
          </span>
        ) : null}
        {keyRefused !== null && problem === null ? (
          <span className="text-meta text-danger" role="alert" id={keyRefusedId}>
            {keyRefused}
          </span>
        ) : null}
      </div>

      <div className="flex flex-col gap-1">
        <label className="text-meta text-muted" htmlFor={titleId}>
          {t('create.titleLabel')}
        </label>
        <Input
          id={titleId}
          value={title}
          onChange={(event) => {
            setTitle(event.target.value);
            setProblem(null);
          }}
          autoComplete="off"
          aria-invalid={problem === 'title' || badTitle}
        />
        {problem === 'title' ? (
          <span className="text-meta text-danger" role="alert">
            {t('create.titleEmpty')}
          </span>
        ) : null}
      </div>

      <DescriptionField
        value={description}
        onChange={setDescription}
        limit={AREA_DESCRIPTION_LIMIT}
        hint={t('descriptionHint')}
      />

      {/* Кнопки выше всего изменчивого: отказ, выросший над ними, увёл бы их
          из-под пальца (`docs/notes/ui.md`). */}
      <div className="flex flex-wrap gap-2">
        <Button type="submit" disabled={create.isPending || tooLong}>
          {create.isPending ? t('create.pending') : t('create.submit')}
        </Button>
        <Button tone="quiet" onClick={onCancel}>
          {t('cancel')}
        </Button>
      </div>

      {create.isError && keyRefused === null ? (
        <Callout tone="danger">
          {errorMessage(create.error)} {t('retrySafe')}
        </Callout>
      ) : null}
    </form>
  );
}

/** Что окно правки знает об области: адрес и нынешние название и описание. */
interface EditableArea {
  address: string;
  title: string;
  description: string;
}

/** Как окно области открывается: своей кнопкой или пунктом меню «⋯» страницы. */
interface DialogPlace {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Своя кнопка окна (строка области в разделе проекта): фокус вернётся на неё. */
  trigger?: ReactNode;
  /** Кнопка «⋯», когда окно открыл пункт меню (`AreaMenu`, TRK-618). */
  returnFocus?: RefObject<HTMLElement | null>;
}

/**
 * Кнопка «Изменить» у области и её окно: название и описание. Ключа в окне нет: он
 * вшит в адрес, на который ссылаются задачи и записи. Имя кнопки называет адрес: в
 * разделе проекта таких кнопок столько, сколько областей.
 */
export function EditArea({ area }: { area: EditableArea }) {
  const [open, setOpen] = useState(false);
  const { t } = useTranslation('area');

  return (
    <EditAreaDialog
      area={area}
      open={open}
      onOpenChange={setOpen}
      trigger={
        <Button tone="quiet" size="sm" aria-label={t('edit.label', { address: area.address })}>
          <Pencil className="size-(--ui-mark)" aria-hidden="true" />
          {t('edit.open')}
        </Button>
      }
    />
  );
}

/** Окно правки области — то же у кнопки строки и у пункта меню страницы области. */
export function EditAreaDialog({
  area,
  open,
  onOpenChange,
  trigger,
  returnFocus,
}: DialogPlace & { area: EditableArea }) {
  const { t } = useTranslation('area');

  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title={t('edit.title', { address: area.address })}
      description={t('edit.intro')}
      closeLabel={t('close')}
      trigger={trigger}
      returnFocus={returnFocus}
    >
      <EditAreaForm area={area} onDone={() => onOpenChange(false)} />
    </Dialog>
  );
}

function EditAreaForm({ area, onDone }: { area: EditableArea; onDone: () => void }) {
  const [title, setTitle] = useState(area.title);
  const [description, setDescription] = useState(area.description);
  const [emptyTitle, setEmptyTitle] = useState(false);
  const update = useUpdateArea();
  const titleId = useId();
  const { t } = useTranslation('area');

  const tooLong = tooLongDescription(description);
  const badTitle = complainsAbout(update.error, 'title');

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (title.trim() === '') {
      setEmptyTitle(true);
      return;
    }
    if (tooLong) return;
    update.mutate(
      { address: area.address, title: title.trim(), description: description.trim() },
      { onSuccess: onDone },
    );
  }

  return (
    <form className="flex flex-col gap-4" onSubmit={submit} noValidate>
      <div className="flex flex-col gap-1">
        <label className="text-meta text-muted" htmlFor={titleId}>
          {t('edit.titleLabel')}
        </label>
        <Input
          id={titleId}
          value={title}
          onChange={(event) => {
            setTitle(event.target.value);
            setEmptyTitle(false);
          }}
          autoComplete="off"
          aria-invalid={emptyTitle || badTitle}
        />
        {emptyTitle ? (
          <span className="text-meta text-danger" role="alert">
            {t('edit.titleEmpty')}
          </span>
        ) : null}
      </div>

      <DescriptionField
        value={description}
        onChange={setDescription}
        limit={AREA_DESCRIPTION_LIMIT}
        hint={t('descriptionHint')}
      />

      <div className="flex flex-wrap gap-2">
        <Button type="submit" disabled={update.isPending || tooLong}>
          {update.isPending ? t('edit.pending') : t('edit.submit')}
        </Button>
        <Button tone="quiet" onClick={onDone}>
          {t('cancel')}
        </Button>
      </div>

      {update.isError ? <Callout tone="danger">{errorMessage(update.error)}</Callout> : null}
    </form>
  );
}

type Move = 'archive' | 'restore';

/**
 * «В архив» у активной области и «Восстановить» у архивной — одна кнопка, чья
 * подпись следует за `archived_at`: фокус после закрытия окна возвращается на неё же.
 * Архив спрашивает ролью `alertdialog`: он замораживает карточку, атрибуты и дело
 * области.
 */
export function AreaArchiving({ address, archived }: { address: string; archived: boolean }) {
  const move: Move = archived ? 'restore' : 'archive';
  const [open, setOpen] = useState(false);
  const { t } = useTranslation('area');
  const Icon = move === 'archive' ? Archive : ArchiveRestore;

  return (
    <AreaArchivingDialog
      address={address}
      archived={archived}
      open={open}
      onOpenChange={setOpen}
      trigger={
        <Button tone="quiet" size="sm" aria-label={t(`${move}.label`, { address })}>
          <Icon className="size-(--ui-mark)" aria-hidden="true" />
          {t(`${move}.open`)}
        </Button>
      }
    />
  );
}

/** Окно архива или восстановления области — у кнопки строки и у пункта меню страницы. */
export function AreaArchivingDialog({
  address,
  archived,
  open,
  onOpenChange,
  trigger,
  returnFocus,
}: DialogPlace & { address: string; archived: boolean }) {
  const move: Move = archived ? 'restore' : 'archive';
  const { t } = useTranslation('area');

  return (
    <Dialog
      alert={move === 'archive'}
      open={open}
      onOpenChange={onOpenChange}
      title={t(`${move}.title`, { address })}
      description={t(`${move}.intro`)}
      closeLabel={t('close')}
      trigger={trigger}
      returnFocus={returnFocus}
    >
      <AreaArchivingForm address={address} move={move} onDone={() => onOpenChange(false)} />
    </Dialog>
  );
}

function AreaArchivingForm({
  address,
  move,
  onDone,
}: {
  address: string;
  move: Move;
  onDone: () => void;
}) {
  const [reason, setReason] = useState('');
  const [emptyReason, setEmptyReason] = useState(false);
  const archive = useArchiveArea();
  const restore = useRestoreArea();
  const action = move === 'archive' ? archive : restore;
  const { t } = useTranslation('area');

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (reason.trim() === '') {
      setEmptyReason(true);
      return;
    }
    action.mutate({ address, reason: reason.trim() }, { onSuccess: onDone });
  }

  return (
    <form className="flex flex-col gap-4" onSubmit={submit} noValidate>
      <ReasonField
        label={t(`${move}.reasonLabel`)}
        value={reason}
        onChange={(next) => {
          setReason(next);
          if (next.trim() !== '') setEmptyReason(false);
        }}
        hint={t(`${move}.reasonHint`)}
        problem={emptyReason ? t(`${move}.reasonEmpty`) : null}
      />

      <div className="flex flex-wrap gap-2">
        <Button type="submit" disabled={action.isPending}>
          {action.isPending ? t(`${move}.pending`) : t(`${move}.submit`)}
        </Button>
        <Button tone="quiet" onClick={onDone}>
          {t('cancel')}
        </Button>
      </div>

      {action.isError ? <Callout tone="danger">{errorMessage(action.error)}</Callout> : null}
    </form>
  );
}
