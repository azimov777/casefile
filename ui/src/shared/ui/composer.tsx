import { useEffect, useId, useState, type ReactNode, type FormEvent } from 'react';
import { EMPTY_DRAFT, clearDraft, readDraft, saveDraft, type Draft } from '@/shared/lib';
import { Button } from './button';
import { Callout } from './callout';
import { Markdown } from './markdown';
import styles from './composer.module.css';

interface ComposerProps {
  /** Метка формы для программы чтения с экрана: «Ответ на DEMO-1#7», «Замечание к DEMO-1». */
  label: string;
  /** Подпись поля: «Ответ», «Замечание». */
  fieldLabel: string;
  /** Ключ черновика в `sessionStorage`: одна форма — один черновик. */
  storageKey: string;
  submitLabel: string;
  pendingLabel: string;
  /** Чем упрекнуть за пустое поле. У ответа и у замечания причина разная. */
  emptyProblem: string;
  placeholder?: string;
  /** Замечание бэкенда к полю `body`, если оно пришло. */
  problem?: string;
  isPending?: boolean;
  /** Отказ отправки словами: рисуется под кнопками и ничего не сдвигает. */
  failure?: ReactNode;
  /**
   * Отправка началась. Зовётся **до** запроса и синхронно: вызывающий обязан успеть
   * закрепить то, что может исчезнуть, раньше, чем перечитывание это уберёт.
   */
  onBegin?: () => void;
  /**
   * Отправить. `true` означает «запись подшита»: черновик стирается, поле пустеет.
   * Ключ повтора приходит сюда, а не рождается у вызывающего: он часть черновика и
   * обязан пережить провал попытки.
   */
  onSubmit: (body: string, idempotencyKey: string) => Promise<boolean>;
}

/**
 * Форма записи в дело: поле markdown, предпросмотр, черновик и упрёк за пустоту.
 *
 * Одна на все формы человека (`../tracker/docs/CONCEPT.md`, 3.4): ответ на вопрос и
 * замечание к задаче отличаются подписями, адресом отправки и последствиями, но не
 * тем, как устроен ввод. Второй экземпляр этой формы рядом означал бы два места, где
 * чинить черновик, предпросмотр и порядок элементов.
 *
 * Порядок элементов — не оформление, а требование: всё, что может появиться и
 * исчезнуть (упрёк, предпросмотр, отказ), стоит **ниже** кнопок. Растёт только то,
 * что под ними, и кнопка отправки не сдвигается ни на пиксель ни в одном состоянии
 * формы — прямо из-под пальца человека, который сейчас нажмёт ещё раз
 * (`docs/notes/ui.md`).
 */
export function Composer({
  label,
  fieldLabel,
  storageKey,
  submitLabel,
  pendingLabel,
  emptyProblem,
  placeholder,
  problem,
  isPending = false,
  failure,
  onBegin,
  onSubmit,
}: ComposerProps) {
  const [draft, setDraft] = useState<Draft>(() => readDraft(storageKey));
  const [showPreview, setShowPreview] = useState(false);
  const [emptyBody, setEmptyBody] = useState(false);
  const bodyId = useId();

  // Форма может пережить смену того, о чём она: соседний вопрос той же задачи меняет
  // ключ черновика, не перемонтируя компонент.
  useEffect(() => {
    setDraft(readDraft(storageKey));
    setEmptyBody(false);
  }, [storageKey]);

  function change(changes: Partial<Draft>) {
    const next = { ...draft, ...changes };
    setDraft(next);
    saveDraft(storageKey, next);

    // Упрёк снимается первым же введённым символом. Сообщение, висящее над полем,
    // в которое человек уже пишет, — это не подсказка, а штраф за прошлое: он
    // сделал ровно то, о чём его попросили, и продолжает видеть красное.
    if (emptyBody && next.body.trim() !== '') setEmptyBody(false);
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    if (draft.body.trim() === '') {
      setEmptyBody(true);
      return;
    }
    setEmptyBody(false);

    // Ключ повтора рождается на первой попытке и переживает её провал: повторная
    // отправка того же черновика идёт с тем же ключом и не заводит вторую запись.
    const idempotencyKey = draft.idempotencyKey === '' ? crypto.randomUUID() : draft.idempotencyKey;
    if (draft.idempotencyKey === '') change({ idempotencyKey });

    const body = draft.body.trim();
    // Раньше запроса и синхронно: дальше начинается гонка кадра потока с ответом
    // сервера, и к её началу закреплять уже поздно.
    onBegin?.();

    if (await onSubmit(body, idempotencyKey)) {
      clearDraft(storageKey);
      setDraft(EMPTY_DRAFT);
      setShowPreview(false);
    }
  }

  const shown = emptyBody ? emptyProblem : problem;

  return (
    <form className={styles.form} onSubmit={(event) => void submit(event)} aria-label={label}>
      <div className={styles.field}>
        <label className={styles.label} htmlFor={bodyId}>
          {fieldLabel}
        </label>
        <textarea
          id={bodyId}
          className={styles.textarea}
          value={draft.body}
          onChange={(event) => change({ body: event.target.value })}
          rows={5}
          placeholder={placeholder}
          aria-invalid={shown !== undefined}
          aria-describedby={shown === undefined ? undefined : `${bodyId}-problem`}
        />
      </div>

      <div className={styles.actions}>
        <Button type="submit" disabled={isPending}>
          {isPending ? pendingLabel : submitLabel}
        </Button>
        <Button tone="quiet" onClick={() => setShowPreview(!showPreview)}>
          {showPreview ? 'Скрыть предпросмотр' : 'Предпросмотр'}
        </Button>
      </div>

      {/* Упрёк не отрывается от поля: связь держит `aria-describedby`, а глазами он
          читается там, где человек только что нажал. */}
      {shown === undefined ? null : (
        <span className={styles.problem} id={`${bodyId}-problem`} role="alert">
          {shown}
        </span>
      )}

      {showPreview && draft.body.trim() !== '' ? (
        <div className={styles.preview}>
          <span className={styles.label}>Как это увидит агент</span>
          <Markdown>{draft.body}</Markdown>
        </div>
      ) : null}

      {failure === undefined ? null : <Callout tone="danger">{failure}</Callout>}
    </form>
  );
}
