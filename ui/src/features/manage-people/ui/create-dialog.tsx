import { useId, useState, type FormEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { ApiError } from '@/shared/api';
import { errorMessage } from '@/shared/errors';
import { Button, Callout, Dialog, Input } from '@/shared/ui';
import type { AccountWithPassword } from '../api/people';
import { useCreateAccount } from '../model/use-people-actions';
import { PasswordChoice, type PasswordMode } from './password-choice';

/** На какое поле жалуется отказ — по коду бэкенда (`../docs/ERRORS.md`). */
const FIELD_OF_CODE: Record<string, 'email' | 'name' | 'password'> = {
  account_email_taken: 'email',
  invalid_email: 'email',
  participant_has_account: 'name',
  account_requires_human: 'name',
  weak_password: 'password',
};

/**
 * Окно «Завести человека»: почта входа, имя-подпись, флаг администратора и пароль.
 *
 * Имя — участник реестра: новый или существующий человек без учётной записи. Оно стоит
 * подписью под каждой записью человека и дальше не меняется, поэтому спрашивается явно,
 * а не выводится из почты: как подписываться, решает не интерфейс.
 *
 * Пароль из ответа сюда не оседает: он уходит вызывающему (`onCreated`), а тот
 * показывает его один раз и забывает при закрытии окна.
 */
export function CreateDialog({
  onClose,
  onCreated,
}: {
  onClose: () => void;
  onCreated: (created: AccountWithPassword) => void;
}) {
  const create = useCreateAccount();
  const [email, setEmail] = useState('');
  const [name, setName] = useState('');
  const [isAdmin, setIsAdmin] = useState(false);
  const [mode, setMode] = useState<PasswordMode>('generate');
  const [password, setPassword] = useState('');
  const [empty, setEmpty] = useState<'email' | 'name' | 'password' | null>(null);
  const emailId = useId();
  const nameId = useId();
  const nameHintId = useId();
  const { t } = useTranslation('people');

  const failed = create.error !== null && create.error !== undefined;
  const complaint =
    create.error instanceof ApiError ? (FIELD_OF_CODE[create.error.code] ?? null) : null;
  // Имя не по шаблону отвергает схема запроса (`validation_error`): шаблон объявлен в ней,
  // и только тогда к отказу приписывается правило имени. Занятое учётной записью имя и имя
  // агента — другие отказы: синтаксис там верен, и правило только сбило бы с толку.
  const badPattern =
    create.error instanceof ApiError &&
    create.error.code === 'validation_error' &&
    JSON.stringify(create.error.details).includes('"name"');
  const badName = complaint === 'name' || badPattern;

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const missing =
      email.trim() === ''
        ? 'email'
        : name.trim() === ''
          ? 'name'
          : mode === 'type' && password === ''
            ? 'password'
            : null;
    setEmpty(missing);
    if (missing !== null) return;

    const created = await create.submit({
      email,
      name,
      isAdmin,
      password: mode === 'type' ? password : null,
    });
    if (created !== null) onCreated(created);
  }

  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      title={t('create.title')}
      description={t('create.intro')}
      closeLabel={t('close')}
    >
      <form className="flex flex-col gap-4" onSubmit={(event) => void submit(event)} noValidate>
        <div className="flex flex-col gap-1">
          <label className="text-meta text-muted" htmlFor={emailId}>
            {t('create.emailLabel')}
          </label>
          <Input
            id={emailId}
            type="email"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            autoComplete="off"
            spellCheck={false}
            aria-invalid={empty === 'email' || complaint === 'email'}
          />
          {empty === 'email' ? (
            <span className="text-meta text-danger" role="alert">
              {t('create.emailEmpty')}
            </span>
          ) : null}
        </div>

        <div className="flex flex-col gap-1">
          <label className="text-meta text-muted" htmlFor={nameId}>
            {t('create.nameLabel')}
          </label>
          <Input
            id={nameId}
            value={name}
            onChange={(event) => setName(event.target.value)}
            autoComplete="off"
            spellCheck={false}
            aria-invalid={empty === 'name' || badName}
            aria-describedby={nameHintId}
            placeholder={t('create.namePlaceholder')}
          />
          <span className="text-meta text-muted" id={nameHintId}>
            {t('create.nameHint')}
          </span>
          {empty === 'name' ? (
            <span className="text-meta text-danger" role="alert">
              {t('create.nameEmpty')}
            </span>
          ) : null}
        </div>

        <label className="flex cursor-pointer items-baseline gap-2">
          <input
            type="checkbox"
            checked={isAdmin}
            onChange={(event) => setIsAdmin(event.target.checked)}
          />
          <span className="max-w-(--ui-text-max) text-meta">{t('create.admin')}</span>
        </label>

        <PasswordChoice
          mode={mode}
          onModeChange={(next) => {
            setMode(next);
            setEmpty(null);
          }}
          password={password}
          onPasswordChange={setPassword}
          invalid={empty === 'password' || complaint === 'password'}
        />
        {empty === 'password' ? (
          <span className="text-meta text-danger" role="alert">
            {t('password.empty')}
          </span>
        ) : null}

        <div className="flex flex-wrap gap-2">
          <Button type="submit" disabled={create.pending}>
            {create.pending ? t('create.pending') : t('create.submit')}
          </Button>
          <Button tone="quiet" onClick={onClose}>
            {t('cancel')}
          </Button>
        </div>

        {failed ? (
          <Callout tone="danger">
            {errorMessage(create.error)} {badPattern ? t('create.nameRule') : null}
          </Callout>
        ) : null}
      </form>
    </Dialog>
  );
}
