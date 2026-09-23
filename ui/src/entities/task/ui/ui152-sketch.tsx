/* ЭСКИЗ UI-152: временный переключатель вариантов раскладки родителя в строке таблицы.
   Вариант берётся из localStorage `ui152-sketch` (a | b | c); без него — раскладка main.
   Файл уходит после выбора владельца. */
import { CornerLeftUp } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { Popover, PopoverContent, PopoverTrigger } from '@/shared/ui';
import { cn } from '@/shared/lib';
import type { TaskParent } from '../api/tasks';
import { TaskParents } from './task-parents';

export const SKETCH: string = (() => {
  try {
    return window.localStorage.getItem('ui152-sketch') ?? '';
  } catch {
    return '';
  }
})();

export function ParentPill({
  parents,
  bare = false,
}: {
  parents: readonly TaskParent[];
  bare?: boolean;
}) {
  const { t } = useTranslation('ui');
  const [first, ...others] = parents;
  if (first === undefined) return null;
  return (
    <Popover>
      <PopoverTrigger
        className={cn(
          'relative z-1 inline-flex max-w-full cursor-pointer items-center gap-0.5 font-mono text-mark text-muted hover:text-text',
          bare
            ? 'border-0 bg-transparent p-0 leading-[1.2] hover:underline'
            : 'rounded-mark border border-line bg-sunken px-1.5 leading-[1.5]',
        )}
        aria-label={`${t('task.parents.label')}: ${first.key}`}
      >
        <CornerLeftUp className={cn('shrink-0', bare ? 'size-2.5' : 'size-3')} aria-hidden="true" />
        <span className="truncate">{first.key}</span>
        {others.length === 0 ? null : <span>+{others.length}</span>}
      </PopoverTrigger>
      <PopoverContent className="w-80 p-2">
        <div className="flex flex-col gap-1">
          {parents.map((p) => (
            <TaskParents key={p.key} parents={[p]} className="[&_a]:whitespace-normal" />
          ))}
        </div>
      </PopoverContent>
    </Popover>
  );
}
