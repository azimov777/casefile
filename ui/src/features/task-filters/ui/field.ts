/*
 * Поле отбора — поиск в строке, исполнитель в панели, запрос — одними утилитами:
 * три копии одной строки разошлись бы при первой же правке одной из них.
 */

/**
 * Поле отбора той же высоты, что кнопки `size="sm"` рядом. Правое поле оставлено под
 * признак черновика (`PendingMark`), который стоит поверх поля у его края.
 */
export const FIELD =
  'min-h-(--ui-control-sm) w-full min-w-0 rounded-mark border bg-surface px-2 text-body text-text placeholder:text-faint focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-focus';

/** Черновик поля: напечатано, но в адрес ещё не уехало. */
export const FIELD_PENDING =
  'pr-24 border-attention-line shadow-[inset_3px_0_0_var(--color-attention-line)]';
