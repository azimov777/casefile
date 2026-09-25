import { useId, useState, type FormEvent, type ReactNode } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { complainsAbout, errorMessage } from '@/shared/errors';
import { Button, Callout, Dialog, Input, QueryState } from '@/shared/ui';
import { participantsQueryOptions, type IssuedToken, type TokenScope } from '../api/access';
import { denialReason } from '../model/problem';
import { useIssueToken } from '../model/use-access-actions';

/**
 * Значение выбора «токен без участника». Именем участника быть не может: шаблон имён —
 * латиница `snake_case` (`app/domain/participants.py`), и звёздочка в него не входит.
 */
const SHARED = '*shared*';

/** Наборы контракта по порядку: умолчание первым. */
const SCOPES: TokenScope[] = ['task', 'main'];

/**
 * Окно «Выпустить токен»: кому, какого набора и как его назвать.
 *
 * Умолчание набора — `task`: он открывает рабочий цикл агента и ничего больше. `main`
 * выбирается явно, и рядом сказано, что он добавляет: запись реестров, то есть выпуск
 * и отзыв доступов на этой установке.
 *
 * Секрет из ответа сюда не оседает: он уходит вызывающему (`onIssued`), а тот
 * показывает его один раз и забывает при закрытии окна (`UI-106#18`).
 *
 * Выбор «за кого» у человека без флага администратора не называет других людей: ключ
 * от чужого имени бэкенд ему не выпустит (`foreign_human`, TRK-114#12), а пункт,
 * который наверняка кончится отказом, в выборе — ловушка, а не возможность.
 *
 * Открывает окно либо своя кнопка «Выпустить» (пропс `trigger`, `participant === null`),
 * либо «Выпустить ему токен» изнутри `AgentDialog` — тогда окно уже открывает вызывающий
 * (`open`/`onOpenChange` страницы), и `trigger` у этого захода нет вовсе: кнопка, что
 * его начала, к этому моменту уже снята вместе со своим окном (`UI-178`, тот же случай,
 * что у окна секрета — «ход работы», а не явная кнопка). Общий `trigger` при этом
 * остаётся смонтированным всегда: Radix не находит, кому вернуть фокус, если сама
 * кнопка-открыватель существует не постоянно.
 */
export function IssueDialog({
  participant,
  me,
  admin,
  open,
  onOpenChange,
  trigger,
  onIssued,
}: {
  /** Кому выпускаем, если участник уже выбран снаружи: после «Завести агента». */
  participant: string | null;
  /** Имя человека этого сеанса: себе ключ выпускает любой. */
  me: string | null;
  /** Флаг администратора учётной записи: ему открыты и чужие люди. */
  admin: boolean;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  trigger?: ReactNode;
  onIssued: (issued: IssuedToken) => void;
}) {
  const { t } = useTranslation('access');

  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      trigger={trigger}
      title={t('issue.title')}
      description={t('issue.intro')}
      closeLabel={t('close')}
    >
      <IssueForm
        participant={participant}
        me={me}
        admin={admin}
        onClose={() => onOpenChange(false)}
        onIssued={onIssued}
      />
    </Dialog>
  );
}

/** Форма выпуска. Живёт в `children` окна и рождается заново на каждый заход. */
function IssueForm({
  participant,
  me,
  admin,
  onClose,
  onIssued,
}: {
  participant: string | null;
  me: string | null;
  admin: boolean;
  onClose: () => void;
  onIssued: (issued: IssuedToken) => void;
}) {
  const participants = useQuery(participantsQueryOptions());
  const issue = useIssueToken();
  const [chosen, setChosen] = useState(participant ?? '');
  const [scope, setScope] = useState<TokenScope>('task');
  const [name, setName] = useState('');
  const [problem, setProblem] = useState<'participant' | 'name' | null>(null);
  const whomId = useId();
  const nameId = useId();
  const nameHintId = useId();
  const scopeName = useId();
  const { t } = useTranslation('access');
  // Род участника — подпись кирпича (`ui`), а не экрана: та же, что у автора записи.
  const { t: brick } = useTranslation('ui');

  const known = (participants.data ?? []).filter(
    (item) => admin || item.kind !== 'human' || item.name === me,
  );
  const failed = issue.error !== null && issue.error !== undefined;
  const badName = complainsAbout(issue.error, 'name');
  const denied = denialReason(issue.error);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    if (chosen === '') {
      setProblem('participant');
      return;
    }
    if (name.trim() === '') {
      setProblem('name');
      return;
    }
    setProblem(null);

    const issued = await issue.submit({
      participant: chosen === SHARED ? null : chosen,
      scope,
      name: name.trim(),
    });
    if (issued !== null) onIssued(issued);
  }

  return (
    <form className="flex flex-col gap-4" onSubmit={(event) => void submit(event)} noValidate>
      <div className="flex flex-col gap-1">
        <label className="text-meta text-muted" htmlFor={whomId}>
          {t('issue.whomLabel')}
        </label>
        {/* Фон и цвет названы явно: у `select` своя системная палитра формы, и без
            объявления цвет достаётся ему от браузера, а не от нашей темы. */}
        <select
          id={whomId}
          className="rounded-mark border border-line-strong bg-surface px-2 py-2 text-body text-text"
          value={chosen}
          aria-invalid={problem === 'participant'}
          onChange={(event) => {
            setChosen(event.target.value);
            setProblem(null);
          }}
        >
          <option value="">{t('issue.whomUnset')}</option>
          {/* Только что заведённый участник стоит в выборе, даже пока реестр
              перечитывается: иначе выпуск ему был бы невозможен ровно в тот момент,
              ради которого окно и открыли. */}
          {known.some((item) => item.name === chosen) ||
          chosen === '' ||
          chosen === SHARED ? null : (
            <option value={chosen}>{chosen}</option>
          )}
          {known.map((item) => (
            <option key={item.id} value={item.name}>
              {item.name} — {brick(`participantKind.${item.kind}`)}
            </option>
          ))}
          <option value={SHARED}>{t('issue.whomShared')}</option>
        </select>
        <QueryState query={participants} loading={t('issue.loadingParticipants')} compact />
        <span className="text-meta text-muted">
          {chosen === SHARED ? t('issue.sharedHint') : t('issue.whomHint')}
        </span>
        {problem === 'participant' ? (
          <span className="text-meta text-danger" role="alert">
            {t('issue.whomEmpty')}
          </span>
        ) : null}
      </div>

      {/* Набор — не оформление доступа, а само право: рядом с каждым сказано, что он
          открывает, потому что выбор делают один раз и навсегда. */}
      <fieldset className="flex min-w-0 flex-col gap-2 border-0 p-0">
        <legend className="text-meta text-muted">{t('issue.scopeLabel')}</legend>
        {SCOPES.map((value) => (
          <label key={value} className="flex cursor-pointer items-baseline gap-2">
            <input
              type="radio"
              name={scopeName}
              value={value}
              checked={scope === value}
              onChange={() => setScope(value)}
            />
            <span className="max-w-(--ui-text-max) text-meta">
              <code className="font-mono text-text">{value}</code>{' '}
              {t(value === 'main' ? 'issue.scopeMainHint' : 'issue.scopeTaskHint')}
            </span>
          </label>
        ))}
      </fieldset>

      <div className="flex flex-col gap-1">
        <label className="text-meta text-muted" htmlFor={nameId}>
          {t('issue.nameLabel')}
        </label>
        <Input
          id={nameId}
          value={name}
          onChange={(event) => {
            setName(event.target.value);
            setProblem(null);
          }}
          autoComplete="off"
          aria-invalid={problem === 'name' || badName}
          aria-describedby={nameHintId}
          placeholder={t('issue.namePlaceholder')}
        />
        <span className="text-meta text-muted" id={nameHintId}>
          {t('issue.nameHint')}
        </span>
        {problem === 'name' ? (
          <span className="text-meta text-danger" role="alert">
            {t('issue.nameEmpty')}
          </span>
        ) : null}
      </div>

      <div className="flex flex-wrap gap-2">
        <Button type="submit" disabled={issue.pending}>
          {issue.pending ? t('issue.pending') : t('issue.submit')}
        </Button>
        <Button tone="quiet" onClick={onClose}>
          {t('cancel')}
        </Button>
      </div>

      {failed ? (
        <Callout tone="danger">
          {errorMessage(issue.error)}{' '}
          {denied !== null
            ? t(`denied.${denied}`)
            : badName
              ? t('issue.nameRule')
              : t('issue.retrySafe')}
        </Callout>
      ) : null}
    </form>
  );
}
