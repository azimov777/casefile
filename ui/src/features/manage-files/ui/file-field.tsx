import { useId } from 'react';
import { Input } from '@/shared/ui';

/**
 * Выбор файла и необязательное новое имя: общая часть загрузки и замены. Поля
 * неуправляемые для файла (значение ввода файла программой не задаётся) и управляемые
 * для имени.
 */
export function FileField({
  fileLabel,
  nameLabel,
  nameHint,
  name,
  onName,
  onFile,
  invalid,
}: {
  fileLabel: string;
  nameLabel: string;
  nameHint: string;
  name: string;
  onName: (name: string) => void;
  onFile: (file: File | null) => void;
  invalid: boolean;
}) {
  const fileId = useId();
  const nameId = useId();
  const hintId = useId();

  return (
    <>
      <div className="flex flex-col gap-1">
        <label className="text-meta text-muted" htmlFor={fileId}>
          {fileLabel}
        </label>
        <input
          id={fileId}
          type="file"
          aria-invalid={invalid}
          onChange={(event) => onFile(event.target.files?.[0] ?? null)}
          className={
            'w-full min-w-0 rounded-mark border border-line-strong bg-surface p-2 text-body text-text ' +
            'aria-invalid:border-danger aria-invalid:bg-danger-soft ' +
            'focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus'
          }
        />
      </div>

      <div className="flex flex-col gap-1">
        <label className="text-meta text-muted" htmlFor={nameId}>
          {nameLabel}
        </label>
        <Input
          id={nameId}
          value={name}
          onChange={(event) => onName(event.target.value)}
          autoComplete="off"
          spellCheck={false}
          aria-describedby={hintId}
        />
        <span className="text-meta text-muted" id={hintId}>
          {nameHint}
        </span>
      </div>
    </>
  );
}
