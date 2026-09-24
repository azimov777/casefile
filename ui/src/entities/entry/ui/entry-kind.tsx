import {
  AlignLeft,
  ArrowRight,
  Check,
  CheckCheck,
  CircleCheck,
  CircleHelp,
  CornerDownRight,
  Flag,
  Link,
  Package,
  Pencil,
  Plus,
  Repeat,
  Search,
  SquarePen,
  StickyNote,
  Unlink,
  User,
} from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { cn } from '@/shared/lib';
import type { EntryType } from '../api/entries';

/**
 * Знак рода записи (решение Д10). В описи и в ленте их по двадцать подряд, и без
 * знака `verdict`, `section_changed` и `decision` различаются только чтением слова.
 *
 * Перечислено ключами через `satisfies Record<EntryType, …>`: тип, добавленный
 * в контракт, роняет сборку, а не остаётся без знака.
 */
const KIND_ICON = {
  summary: AlignLeft,
  decision: Check,
  attempt: Repeat,
  finding: Search,
  artifact: Package,
  question: CircleHelp,
  answer: CornerDownRight,
  verdict: CircleCheck,
  remark: Flag,
  resolution: CheckCheck,
  note: StickyNote,
  created: Plus,
  status_changed: ArrowRight,
  section_changed: SquarePen,
  field_changed: Pencil,
  assignee_changed: User,
  link_added: Link,
  link_removed: Unlink,
} satisfies Record<EntryType, typeof Check>;

/**
 * Цвет знака. Красится только то, что меняет решение человека: запись агента,
 * которая что-то решает, вопрос, который ждёт ответа, замечание и вердикт.
 * Служебные записи трекера остаются служебным уровнем — их в деле большинство.
 */
const KIND_COLOR = {
  summary: 'text-accent',
  decision: 'text-accent',
  attempt: 'text-muted',
  finding: 'text-muted',
  artifact: 'text-muted',
  question: 'text-attention',
  answer: 'text-muted',
  verdict: 'text-positive',
  remark: 'text-danger',
  resolution: 'text-positive',
  note: 'text-muted',
  created: 'text-faint',
  status_changed: 'text-faint',
  section_changed: 'text-faint',
  field_changed: 'text-faint',
  assignee_changed: 'text-faint',
  link_added: 'text-faint',
  link_removed: 'text-faint',
} satisfies Record<EntryType, string>;

interface EntryKindProps {
  type: EntryType;
  /**
   * Показывать ли идентификатор типа рядом. Там, где места нет (нить времени в ленте),
   * род всё равно называется — визуально скрытым текстом.
   */
  withName?: boolean;
  className?: string;
}

/** Род записи: знак и идентификатор типа из контракта рядом. */
export function EntryKind({ type, withName = true, className }: EntryKindProps) {
  const { t } = useTranslation('ui');

  return (
    <span
      data-mark="kind"
      className={cn('inline-flex items-center gap-1.5 whitespace-nowrap', className)}
    >
      <EntryTypeIcon type={type} />
      {/* Название словами — для диктора: `section_changed` вслух не читается. */}
      <span className="sr-only">{t(`entry.type.${type}`)}: </span>
      {/* Идентификатор и скрытым остаётся идентификатором — моноширинным, как видимый. */}
      <span className={withName ? 'font-mono text-mark text-muted' : 'font-mono sr-only'}>
        {type}
      </span>
    </span>
  );
}

/**
 * Только знак рода, без идентификатора и подписи для диктора: панель отбора записей
 * дела (UI-137) ставит его рядом со своим собственным `<code>{type}</code>` внутри
 * кнопки переключателя и не должна тащить вместе с ним весь `EntryKind`.
 */
export function EntryTypeIcon({ type, className }: { type: EntryType; className?: string }) {
  const Icon = KIND_ICON[type];
  return (
    <Icon
      className={cn('size-(--ui-mark) shrink-0', KIND_COLOR[type], className)}
      aria-hidden="true"
    />
  );
}
