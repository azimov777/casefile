import { useId } from 'react';
import { Textarea } from '@/shared/ui';

/**
 * Причина — обязательное поле: пустое не отправляется, и упрёк стоит под полем,
 * связанный с ним `aria-describedby`. `required` у поля — для программы чтения с
 * экрана; проверку браузера форма гасит (`noValidate`), чтобы упрёк был нашим словом
 * на языке интерфейса, а не всплывашкой браузера.
 */
export function ReasonField({
  label,
  value,
  onChange,
  hint,
  problem,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  hint: string;
  problem: string | null;
}) {
  const id = useId();
  const hintId = useId();
  const problemId = useId();

  return (
    <div className="flex flex-col gap-1">
      <label className="text-meta text-muted" htmlFor={id}>
        {label}
      </label>
      <Textarea
        id={id}
        rows={3}
        required
        value={value}
        onChange={(event) => onChange(event.target.value)}
        aria-invalid={problem !== null}
        aria-describedby={problem === null ? hintId : `${hintId} ${problemId}`}
      />
      <span className="text-meta text-muted" id={hintId}>
        {hint}
      </span>
      {problem === null ? null : (
        <span className="text-meta text-danger" id={problemId} role="alert">
          {problem}
        </span>
      )}
    </div>
  );
}
