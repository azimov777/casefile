/**
 * Ссылки на задачи и записи в свободном тексте: `TRK-42`, `TRK-42#12` и запись дела
 * проекта `TRK#7`.
 *
 * Такие ссылки агенты пишут руками в телах записей, заголовках и разделах, а бэкенд
 * их не размечает: в контракте это просто текст (`refs` рядом — отдельный список,
 * и он не говорит, где именно в теле ссылка стоит). Значит превращать текст в ссылку —
 * дело интерфейса, и делать это надо в одном месте на всё приложение.
 */

/** Куда указывает ссылка: на задачу или на конкретную запись её дела. */
export interface TaskRef {
  key: string;
  /** Номер записи внутри задачи; `null` — ссылка на задачу целиком. */
  entryNo: number | null;
}

/** Кусок строки: обычный текст или ссылка с готовым адресом приложения. */
export type TextPart =
  { kind: 'text'; value: string } | { kind: 'ref'; value: string; href: string };

/**
 * Ключ задачи в верхнем регистре: `КЛЮЧ-номер`, ключ проекта — латиница и цифры
 * (`../app/domain/projects.py`, `PROJECT_KEY_PATTERN`). Нижний регистр бэкенд
 * принимает, но канонический вид — верхний, и только его мы считаем ссылкой:
 * иначе в ссылку превращалось бы любое `pull-2` из текста.
 *
 * Вторая ветка — запись дела проекта `TRK#7` (TRK-156, `../docs/CONCEPT.md`, 3.4):
 * ключ проекта и номер без номера задачи. Её не спутать с `TRK-42#3` — дефис есть
 * только в ключе задачи. Сам ключ проекта без номера записи (`TRK`) ссылкой не
 * становится: в прозе это обычное слово заглавными.
 */
const TASK_REF = /\b([A-Z][A-Z0-9]{1,15})(?:-(\d+)(?:#(\d+))?|#(\d+))\b/g;

/** Разбирает строку на обычный текст и ссылки, сохраняя порядок и исходное написание. */
export function splitTaskRefs(text: string): TextPart[] {
  const parts: TextPart[] = [];
  let last = 0;

  for (const match of text.matchAll(TASK_REF)) {
    const at = match.index;
    if (at > last) parts.push({ kind: 'text', value: text.slice(last, at) });

    const [value, project = '', number, entry, projectEntry] = match;
    parts.push({
      kind: 'ref',
      value,
      href:
        number === undefined
          ? projectHref(project, Number(projectEntry))
          : taskRefHref({
              key: `${project}-${number}`,
              entryNo: entry === undefined ? null : Number(entry),
            }),
    });
    last = at + value.length;
  }

  if (last < text.length) parts.push({ kind: 'text', value: text.slice(last) });
  return parts;
}

/**
 * Адрес экрана проекта; с номером записи — экран с раскрытой записью его дела.
 *
 * Тем же параметром `entry`, что и карточка задачи, и по той же причине: ссылка на
 * запись ведёт к её владельцу, а не в ленту (`taskRefHref` ниже). Ленты у проекта нет
 * вовсе (`docs/CONCEPT.md`, 3).
 */
export function projectHref(key: string, entryNo: number | null = null): string {
  const path = `/projects/${key}`;
  return entryNo === null ? path : `${path}?entry=${entryNo}`;
}

/**
 * Адрес карточки задачи; ссылка на запись открывает карточку и раскрывает эту запись.
 *
 * **Одно правило на всё приложение.** Ссылка на запись ведёт в карточку, а не в ленту
 * дела, и так же ведут уведомление о вопросе и подтверждение ответа. Причина: карточка
 * — единственное место, где с записью можно что-то сделать, а не только прочитать её.
 * Вопрос, на который человека позвали, отвечается там же; лента только показывает.
 *
 * Номер записи едет параметром, а не якорем `#12`, хотя в тексте ссылка выглядит именно
 * так: якорь для браузера — цель прокрутки к элементу с таким `id`, а нам нужно раскрыть
 * запись и дочитать её тело. Это состояние страницы, и живёт оно там же, где остальное
 * состояние адреса (`CONVENTIONS.md`, «Состояние»).
 */
export function taskRefHref(ref: TaskRef): string {
  const path = `/tasks/${ref.key}`;
  return ref.entryNo === null ? path : `${path}?entry=${ref.entryNo}`;
}

/**
 * Адрес ленты дела; с номером записи — лента, доведённая до этой записи и её пометившая.
 *
 * Тем же параметром `entry`, что и карточка: одно действие человека — «покажи мне
 * запись N» — не должно называться в адресе двумя разными способами в зависимости
 * от того, на какой он странице. Раньше лента пользовалась якорем `#N`, и это было
 * второе имя того же самого.
 */
export function caseHref(key: string, entryNo: number | null = null): string {
  const path = `/tasks/${key}/case`;
  return entryNo === null ? path : `${path}?entry=${entryNo}`;
}

/** Номер записи из адреса: чужое значение — это отсутствие номера, а не ошибка. */
export function readEntryNo(value: string | null): number | null {
  if (value === null) return null;
  const no = Number(value);
  return Number.isInteger(no) && no > 0 ? no : null;
}

/**
 * Ключ проекта, которому принадлежит задача: `UI-38` → `UI`.
 *
 * Разбор ключа, а не вычисление за бэкенд: ключ задачи по контракту состоит из ключа
 * проекта и номера, и проект читается из него так же, как его читает человек.
 * Спрашивать ради этого задачу отдельно значило бы платить запросом за то, что уже
 * написано в адресе.
 *
 * `null` — строка ключом не является: показывать проект тогда нечего.
 */
export function projectOfKey(key: string): string | null {
  const match = /^([A-Za-z][A-Za-z0-9]{1,15})-\d+$/.exec(key);
  return match?.[1] === undefined ? null : match[1].toUpperCase();
}
