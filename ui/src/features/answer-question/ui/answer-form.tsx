import { useEffect, useId, useState, type FormEvent } from 'react';
import { ApiError } from '@/shared/api';
import { errorMessage } from '@/shared/errors';
import { Button, Callout, Markdown } from '@/shared/ui';
import {
  EMPTY_DRAFT,
  clearDraft,
  draftKey,
  readDraft,
  saveDraft,
  splitRefs,
  type AnswerDraft,
} from '../model/draft';
import { useAnswerQuestion } from '../model/use-answer-question';
import styles from './answer-form.module.css';

interface AnswerFormProps {
  taskKey: string;
  questionNo: number;
  /** Что сделать после удачного ответа: закрыть форму, увести со страницы. */
  onAnswered?: () => void;
}

/**
 * Форма ответа на вопрос агента.
 *
 * Черновик пишется в `sessionStorage` на каждое изменение: человек уходит смотреть
 * соседнюю задачу и возвращается дописывать.
 */
export function AnswerForm({ taskKey, questionNo, onAnswered }: AnswerFormProps) {
  const storageKey = draftKey(taskKey, questionNo);
  const [draft, setDraft] = useState<AnswerDraft>(() => readDraft(storageKey));
  const [showPreview, setShowPreview] = useState(false);
  const [emptyBody, setEmptyBody] = useState(false);
  const answer = useAnswerQuestion();

  const bodyId = useId();
  const refsId = useId();

  // Форма живёт под каждым вопросом, и вопрос может смениться без перемонтирования.
  useEffect(() => {
    setDraft(readDraft(storageKey));
    setEmptyBody(false);
  }, [storageKey]);

  function change(changes: Partial<AnswerDraft>) {
    const next = { ...draft, ...changes };
    setDraft(next);
    saveDraft(storageKey, next);
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    if (draft.body.trim() === '') {
      setEmptyBody(true);
      return;
    }
    setEmptyBody(false);

    // Ключ повтора рождается на первой попытке и переживает её провал: повторная
    // отправка того же черновика идёт с тем же ключом и не заводит второй ответ.
    const idempotencyKey = draft.idempotencyKey === '' ? crypto.randomUUID() : draft.idempotencyKey;
    if (draft.idempotencyKey === '') change({ idempotencyKey });

    answer.mutate(
      {
        taskKey,
        questionNo,
        body: draft.body.trim(),
        refs: splitRefs(draft.refs),
        idempotencyKey,
      },
      {
        onSuccess: () => {
          clearDraft(storageKey);
          setDraft(EMPTY_DRAFT);
          onAnswered?.();
        },
      },
    );
  }

  const fields = answer.error instanceof ApiError ? answer.error.fields : null;

  return (
    <form
      className={styles.form}
      onSubmit={submit}
      aria-label={`Ответ на ${taskKey}#${questionNo}`}
    >
      <div className={styles.field}>
        <label className={styles.label} htmlFor={bodyId}>
          Ответ
        </label>
        <textarea
          id={bodyId}
          className={styles.textarea}
          value={draft.body}
          onChange={(event) => change({ body: event.target.value })}
          rows={5}
          placeholder="Markdown. Ссылки вида DEMO-2 и DEMO-2#7 станут ссылками."
          aria-invalid={emptyBody || fields?.body !== undefined}
          aria-describedby={emptyBody ? `${bodyId}-problem` : undefined}
        />
        {emptyBody ? (
          <span className={styles.problem} id={`${bodyId}-problem`} role="alert">
            Пустой ответ отправить нельзя: агенту нужен текст, а не факт нажатия кнопки.
          </span>
        ) : null}
        {fields?.body === undefined ? null : (
          <span className={styles.problem} role="alert">
            {fields.body}
          </span>
        )}
      </div>

      <div className={styles.field}>
        <label className={styles.label} htmlFor={refsId}>
          Ссылки на записи и задачи
        </label>
        <input
          id={refsId}
          className={styles.input}
          value={draft.refs}
          onChange={(event) => change({ refs: event.target.value })}
          placeholder="DEMO-2#7, DEMO-3 — через запятую или пробел"
          autoComplete="off"
          aria-invalid={fields?.refs !== undefined}
        />
        {fields?.refs === undefined ? null : (
          <span className={styles.problem} role="alert">
            {fields.refs}
          </span>
        )}
      </div>

      {showPreview && draft.body.trim() !== '' ? (
        <div className={styles.preview}>
          <span className={styles.label}>Как это увидит агент</span>
          <Markdown>{draft.body}</Markdown>
        </div>
      ) : null}

      <div className={styles.actions}>
        <Button type="submit" disabled={answer.isPending}>
          {answer.isPending ? 'Отправляем…' : 'Ответить'}
        </Button>
        <Button tone="quiet" onClick={() => setShowPreview(!showPreview)}>
          {showPreview ? 'Скрыть предпросмотр' : 'Предпросмотр'}
        </Button>
      </div>

      {answer.isError ? (
        <Callout tone="danger">
          {errorMessage(answer.error)} Повторная отправка не заведёт второй ответ: ключ повтора у
          попытки тот же.
        </Callout>
      ) : null}
    </form>
  );
}
