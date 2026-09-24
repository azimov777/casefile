import { Ban, CornerDownRight, CornerLeftUp, Link2, Lock } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { cn } from '@/shared/lib';
import type { LinkKind } from '../api/task-package';

/**
 * Знак вида связи (UI-125). Вид назван от лица этой задачи: `blocked_by` — то, что
 * держит именно её, `blocks` — то, что держит она сама, `parent` — она родитель
 * перечисленных, `child` — она их ребёнок, `relates` — связь, которая никого ни к чему не обязывает.
 *
 * Перечислено ключами через `satisfies Record<LinkKind, …>`: вид, добавленный
 * в контракт, роняет сборку, а не остаётся без знака и без места в порядке групп.
 */
const KIND_ICON = {
  // Знак показывает, где в дереве стоят перечисленные под ним задачи (UI-166): под
  // `parent` — дочерние, они ниже (`CornerDownRight`); под `child` — родитель, он выше,
  // тем же знаком, что у подписи родителя в строке и на карточке (`task-parents.tsx`).
  blocked_by: Lock,
  blocks: Ban,
  parent: CornerDownRight,
  child: CornerLeftUp,
  relates: Link2,
} satisfies Record<LinkKind, typeof Lock>;

/**
 * Цвет знака. Красится только то, что меняет решение человека (тот же принцип, что
 * у `entry-kind.tsx`): `blocked_by` красится ровно тем тоном, каким признак
 * «заблокирована» красит замок в списке задач (`feature-marks.tsx`, `text-danger`)
 * — это одно и то же положение дел, увиденное с двух концов связи. Остальные виды —
 * обычный ход дел, служебного уровня.
 */
const KIND_COLOR = {
  blocked_by: 'text-danger',
  blocks: 'text-muted',
  parent: 'text-muted',
  child: 'text-muted',
  relates: 'text-faint',
} satisfies Record<LinkKind, string>;

/**
 * Порядок групп по значимости, а не по появлению связи в ответе (владелец, UI-125):
 * то, что держит задачу, стоит первым, необязывающая связь — последней.
 *
 * Массив, а не `Object.keys` вида ради самого перечня — здесь важен порядок, а не
 * факт присутствия, — но полноту стережёт `ORDER_SET` рядом тем же приёмом, что
 * `TASK_STATUSES` в `api/tasks.ts`: вид, забытый здесь, роняет сборку, а не тихо
 * пропадает из группировки.
 */
const ORDER_SET = {
  blocked_by: true,
  blocks: true,
  // Родитель выше дочерних (UI-166): `child` — группа с родителем этой задачи.
  child: true,
  parent: true,
  relates: true,
} satisfies Record<LinkKind, true>;

export const LINK_KIND_ORDER = Object.keys(ORDER_SET) as LinkKind[];

interface LinkKindMarkProps {
  kind: LinkKind;
  className?: string;
}

/**
 * Заголовок группы связей одного вида: знак, идентификатор контракта моноширинным —
 * как есть, не обрезается (`ui/docs/CONCEPT.md`, 6) — и подпись на языке человека
 * рядом из словаря: она стоит рядом с идентификатором, а не вместо него.
 */
export function LinkKindMark({ kind, className }: LinkKindMarkProps) {
  const Icon = KIND_ICON[kind];
  const { t } = useTranslation('ui');

  /*
   * Части стоят по базовой линии текста, а знак — по центру строки (UI-168). Прежде ряд
   * был `items-center`, а первым в нём шёл знак: у svg базовой линии нет, и базовой
   * линией всего ряда браузер брал низ знака. Счётчик рядом в заголовке группы
   * выравнивался по ней и стоял на 3–4 px ниже идентификатора и подписи, а сами они
   * расходились ещё на 0,7 px — разный кегль, поставленный по центру, а не по линии.
   * `self-center` выводит знак из выравнивания по линии, и базовой линией ряда
   * становится идентификатор — та же, что у подписи и счётчика.
   */
  return (
    <span
      data-mark="link-kind"
      className={cn('inline-flex items-baseline gap-1.5 whitespace-nowrap', className)}
    >
      <Icon
        className={cn('size-(--ui-mark) shrink-0 self-center', KIND_COLOR[kind])}
        aria-hidden="true"
      />
      <span className="font-mono text-mark text-muted">{kind}</span>
      <span className="text-meta text-muted">{t(`task.links.kind.${kind}`)}</span>
    </span>
  );
}
