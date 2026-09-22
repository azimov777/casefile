import { useId } from 'react';
import { useTranslation } from 'react-i18next';
import { Input } from '@/shared/ui';

/** Как задать пароль: сгенерировать трекером или вписать самому. */
export type PasswordMode = 'generate' | 'type';

/**
 * Выбор пароля товарищу: трекер генерирует его сам (умолчание) или администратор вписывает
 * свой. Требования к паролю — от 12 символов — называет подсказка, а проверяет бэкенд
 * (`weak_password`): длину клиент не считает за него.
 */
export function PasswordChoice({
  mode,
  onModeChange,
  password,
  onPasswordChange,
  invalid,
}: {
  mode: PasswordMode;
  onModeChange: (mode: PasswordMode) => void;
  password: string;
  onPasswordChange: (password: string) => void;
  /** Отказ жалуется на пароль или поле оставлено пустым. */
  invalid: boolean;
}) {
  const { t } = useTranslation('people');
  const groupName = useId();
  const inputId = useId();
  const hintId = useId();

  return (
    <fieldset className="flex min-w-0 flex-col gap-2 border-0 p-0">
      <legend className="text-meta text-muted">{t('password.legend')}</legend>
      <label className="flex cursor-pointer items-baseline gap-2">
        <input
          type="radio"
          name={groupName}
          value="generate"
          checked={mode === 'generate'}
          onChange={() => onModeChange('generate')}
        />
        <span className="max-w-(--ui-text-max) text-meta">{t('password.generate')}</span>
      </label>
      <label className="flex cursor-pointer items-baseline gap-2">
        <input
          type="radio"
          name={groupName}
          value="type"
          checked={mode === 'type'}
          onChange={() => onModeChange('type')}
        />
        <span className="max-w-(--ui-text-max) text-meta">{t('password.type')}</span>
      </label>

      {mode === 'type' ? (
        <div className="flex flex-col gap-1 pl-6">
          <label className="text-meta text-muted" htmlFor={inputId}>
            {t('password.label')}
          </label>
          <Input
            id={inputId}
            type="password"
            value={password}
            onChange={(event) => onPasswordChange(event.target.value)}
            autoComplete="new-password"
            spellCheck={false}
            aria-invalid={invalid}
            aria-describedby={hintId}
          />
          <span className="text-meta text-muted" id={hintId}>
            {t('password.hint')}
          </span>
        </div>
      ) : null}
    </fieldset>
  );
}
