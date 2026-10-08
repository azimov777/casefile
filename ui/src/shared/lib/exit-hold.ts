import { useCallback, useEffect, useRef, useState, type RefCallback } from 'react';

/**
 * Держать узел, пока идёт выход.
 *
 * Движение на выходе некому показать: `{open ? … : null}` убирает узел в том же кадре,
 * в котором человек нажал, и анимировать становится нечего. Библиотеки анимации
 * в проекте нет, а Radix держит узел только у себя (`Presence` ждёт `animationend`
 * на своём содержимом), поэтому задержка размонтирования живёт здесь — **одна на весь
 * интерфейс**. Второй такой заводить нельзя: разойдясь на десять миллисекунд, две копии
 * дадут в одном месте обрубленный выход, а в другом — узел, висящий после движения.
 *
 * **Конец выхода — конец движений самого узла**, а не срок, отсчитанный снаружи (UI-111).
 * Узел отдаёт задержке свой корень (`ref`), и она снимает его, когда кончились все
 * идущие движения его поддерева: переход места, анимация карточки, прозрачность
 * раскрытия. Срок снаружи не годится, потому что снаружи не видно, когда движение
 * началось: переход начинается кадром, а не коммитом, — а на нажатии React выполняет
 * эффекты в конце коммита, раньше этого кадра, — и не всегда первым кадром после
 * коммита: переход, начатый вместе с анимацией на композиторе, ждёт общего с ней
 * времени старта и начинается кадром позже (замер `UI-111#6`). Таймер от коммита снимал
 * узел, когда место прошло три четверти пути, и остаток стопка проходила одним кадром.
 *
 * Длительность выхода не написана числом, а прочитана из `--motion-fast` живого
 * документа (см. `exitDurationMs`), и нужна она теперь для одного: понять, что кадра
 * не было вовсе. `prefers-reduced-motion` переопределяет токен в `0.01ms`
 * (`shared/styles/index.css`) — движение короче промежутка до кадра, показывать нечего,
 * и узел уходит сразу, до следующего кадра: человек, попросивший не двигать интерфейс,
 * не получает узлов, зависающих без всякого движения. То же в фоновой вкладке — кадров
 * там нет. По словарю движения (UI-59) **любой** выход идёт `--motion-fast`, поэтому
 * выбирать длительность вызывающему негде и нечем: параметра нет намеренно.
 *
 * Вход хук тоже различает, и по той же причине: движение отвечает на событие
 * (TRK#238). Узел, стоявший с самого начала, никуда не приезжал — страницу
 * просто открыли, — и признак `entering` у него ложь. Без этого раскрытия въезжали бы
 * на каждой загрузке страницы: замерено на доске, четыре столбца из четырёх.
 *
 * Формы две, а исполнение одно: `useExitHold` держит один узел (раскрытие по
 * `aria-expanded`), `useExitHoldList` — узлы списка, который редеет по одному
 * (стопка уведомлений). Показ сам по себе не двигается: хук говорит, **что рисовать**,
 * **кто въезжает** и **кто уже уходит**, и смотрит на движения узла только затем,
 * чтобы узнать, кончились ли они; чем именно двигать — дело места (для раскрытия
 * в потоке это `shared/ui/reveal.tsx`).
 */

/** Один придержанный узел: что рисовать, въезжает ли он и идёт ли уже выход. */
export interface ExitHold {
  /** Узел рисуют: он либо показан, либо доживает выход. */
  held: boolean;
  /** Из показа его уже убрали: идут последние кадры. */
  leaving: boolean;
  /** Узел появился в ответ на событие, а не стоял с самого начала: ему положен вход. */
  entering: boolean;
  /**
   * Ставится на корень придержанного узла: по его движениям задержка узнаёт, что выход
   * кончился. Без ссылки узел держит срок `--motion-fast` от коммита — а он кончается
   * раньше движения, и выход обрывается.
   */
  ref: RefCallback<Element>;
}

/** Придержанный элемент списка. */
export interface Held<T> {
  /** Ключ показа, он же ключ React: по нему элемент узнают между отрисовками. */
  key: string;
  /** Сам элемент; у уходящего — тот, каким его показывали в последний раз. */
  item: T;
  /** Из показа его уже убрали: идут последние кадры. */
  leaving: boolean;
  /** Элемент появился в ответ на событие, а не стоял с самого начала. */
  entering: boolean;
  /** Ставится на корень узла элемента — см. `ExitHold.ref`. */
  ref: RefCallback<Element>;
}

/** Метка единственного узла в списочном исполнении: ключ ему не нужен, но нужен движку. */
const ONE = 'held';

/** Ключ строки — она сама: списку из одной метки другого и не надо. */
function itself(key: string): string {
  return key;
}

/**
 * Ключи уходящих склеиваются в подпись для зависимостей эффекта; в ключах его нет.
 * Записан экранированием, а не самим символом: нулевой байт в исходнике делает файл
 * для git двоичным, и его правки не видно в `git diff`.
 */
const SEPARATOR = '\u0000';

/**
 * Сколько длится выход, в миллисекундах.
 *
 * Читается из `--motion-fast` корня документа, а не пишется числом: число вывело бы
 * задержку из-под `prefers-reduced-motion`, который гасит движение переопределением
 * самого токена, а не перечислением переходов (`shared/styles/index.css`).
 *
 * Токена нет вовсе — держать нечего: в jsdom стилей не загружено, и узел уходит сразу,
 * как уходил до всякого движения.
 */
export function exitDurationMs(): number {
  if (typeof document === 'undefined') return 0;

  const value = getComputedStyle(document.documentElement).getPropertyValue('--motion-fast').trim();
  const number = Number.parseFloat(value);
  if (!Number.isFinite(number)) return 0;

  // Браузер печатает токен как написано: `120ms` или `0.12s`. Единица важна: секунды,
  // принятые за миллисекунды, дали бы задержку в тысячу раз короче движения.
  return value.endsWith('ms') ? number : number * 1000;
}

/**
 * Идущие движения поддерева, у которых есть конец. Кончившееся (анимация с заливкой
 * `both` остаётся в выдаче и после конца) и снятое не держат; бесконечное тоже —
 * выхода у него нет, и узел висел бы вечно.
 */
function motionsOf(node: Element): Animation[] {
  return node.getAnimations({ subtree: true }).filter((motion) => {
    if (motion.playState !== 'running') return false;
    const end = Number(motion.effect?.getComputedTiming().endTime ?? Number.POSITIVE_INFINITY);
    return Number.isFinite(end);
  });
}

/**
 * Ждёт конца выхода одного узла и зовёт `release`. Отдаёт отмену: элемент вернули
 * в показ раньше, чем выход кончился.
 *
 * Узел снимается, когда кончились все идущие движения его поддерева. Промис `finished`
 * разрешается в том кадре, где движение дошло до конца, а снятие React делает своим
 * обычным порядком, отдельной задачей — после того, как этот кадр нарисован. Поэтому
 * последний кадр с узлом всегда конечный: место в нём уже схлопнулось само, а не
 * обнуляется снятием узла. Кончившись, движения проверяются ещё раз: пришедшее на смену
 * посреди выхода тоже дожидаются.
 *
 * Срок `duration` от коммита решает одно: был ли с начала выхода хоть один кадр. Не было —
 * движение короче промежутка до кадра (погашено) или вкладка в фоне, и узел уходит
 * сразу. Узла нет или браузер движений не отдаёт (jsdom) — узел держит этот срок,
 * как держал до UI-111.
 */
function awaitExit(node: Element | undefined, duration: number, release: () => void): () => void {
  if (node === undefined || !('getAnimations' in node)) {
    const timer = setTimeout(release, duration);
    return () => clearTimeout(timer);
  }

  const watched: Element = node;
  let over = false;
  let drawn = false;
  const frame = requestAnimationFrame(() => {
    drawn = true;
  });
  const timer = setTimeout(() => {
    if (!drawn) finish();
  }, duration);

  function stop(): void {
    over = true;
    cancelAnimationFrame(frame);
    clearTimeout(timer);
  }

  function finish(): void {
    if (over) return;
    stop();
    release();
  }

  function settle(): void {
    if (over) return;
    const running = motionsOf(watched);
    // Движений нет — ждать нечего: узел уходит, как только это стало известно.
    if (running.length === 0) {
      finish();
      return;
    }
    // Снятое посреди выхода движение отклоняет `finished` — это тоже его конец, а не
    // ошибка: что идёт вместо него, покажет следующая проверка.
    void Promise.allSettled(running.map((motion) => motion.finished)).then(settle);
  }

  settle();
  return stop;
}

/**
 * Держит один узел до конца выхода.
 *
 * `held` — рисовать ли узел, `leaving` — идёт ли выход, `ref` — на корень узла. Пока
 * `leaving`, узел стоит в разметке со своим содержимым: это те самые кадры, ради которых
 * он и придержан.
 */
export function useExitHold(shown: boolean): ExitHold {
  const held = useExitHoldList(shown ? [ONE] : [], itself);
  const only = held[0];

  return {
    held: only !== undefined,
    leaving: only?.leaving ?? false,
    entering: only?.entering ?? false,
    ref: only?.ref ?? unheld,
  };
}

/** Ссылка узла, которого не рисуют: ставить её некуда, но форма у задержки одна. */
function unheld(): void {}

/**
 * Держит узлы списка, который редеет по одному.
 *
 * Уходящий остаётся на своём месте в выдаче, а не уезжает в конец: стопка, где
 * закрываемая карточка перепрыгнула вниз, движением ничего не объясняет. Новые
 * элементы встают в конец.
 *
 * `keyOf` обязан давать разным элементам разные ключи: по ключу элемент узнают между
 * отрисовками, и одинаковые ключи склеили бы два узла в один. `ref` каждого элемента
 * ставится на корень его узла.
 */
export function useExitHoldList<T>(
  shown: readonly T[],
  keyOf: (item: T) => string,
): readonly Held<T>[] {
  /** Состав показа: только ключи и их порядок. Содержимое живёт в `shown` и в `seen`. */
  const [order, setOrder] = useState<readonly string[]>(() => shown.map(keyOf));
  /** Последнее виденное содержимое: у уходящего его больше неоткуда взять. */
  const seen = useRef(new Map<string, T>());
  /** Ожидание конца выхода по ключу — его отмена. */
  const holds = useRef(new Map<string, () => void>());
  /** Корни узлов по ключу: с них читаются движения выхода. */
  const nodes = useRef(new Map<string, Element>());
  /**
   * Ссылка на корень по ключу — одна на всю жизнь элемента: новая на каждой отрисовке
   * заставила бы React снимать и ставить её заново.
   */
  const refs = useRef(new Map<string, RefCallback<Element>>());
  /*
   * Кто появился после первой отрисовки. Стоявшему с самого начала вход не положен:
   * никакого события не было — страницу открыли, и раскрытие уже было раскрыто.
   * Считается это здесь, а не в показе: показ видит только «узел есть», и отличить
   * въезжающий от загруженного вместе со страницей ему нечем.
   */
  const born = useRef(new Set<string>());

  const refOf = (key: string): RefCallback<Element> => {
    const known = refs.current.get(key);
    if (known !== undefined) return known;

    const ref: RefCallback<Element> = (node) => {
      if (node === null) nodes.current.delete(key);
      else nodes.current.set(key, node);
    };
    refs.current.set(key, ref);
    return ref;
  };

  const alive = new Map(shown.map((item): [string, T] => [keyOf(item), item]));

  /*
   * Состав пополняется во время отрисовки, а не эффектом: узел, который человек только
   * что открыл, обязан появиться в этом же кадре. Эффект дал бы его через один — то
   * есть вход опаздывал бы ровно на то, что здесь чинится. Приведение состояния
   * к свойствам во время отрисовки React разрешает и перерисовывает сразу; цикла тут
   * нет: после обновления добавлять уже нечего.
   */
  const added = [...alive.keys()].filter((key) => !order.includes(key));
  const composition = added.length === 0 ? order : [...order, ...added];
  if (added.length > 0) {
    // Пришедших помнит ссылка, а не сама выдача: показ обязан увидеть признак входа
    // в том же кадре, в котором узел встал в разметку, — иначе `@starting-style`
    // ему уже нечего начинать. На первой отрисовке `added` пуст по построению.
    for (const key of added) born.current.add(key);
    setOrder(composition);
  }

  const list = composition.flatMap((key): Held<T>[] => {
    const item = alive.get(key) ?? seen.current.get(key);
    return item === undefined
      ? []
      : [
          {
            key,
            item,
            leaving: !alive.has(key),
            entering: born.current.has(key),
            ref: refOf(key),
          },
        ];
  });

  // Содержимое запоминается после отрисовки: к моменту, когда элемент пропал из показа,
  // здесь лежит он же, каким его рисовали в прошлый раз.
  useEffect(() => {
    for (const [key, item] of alive) seen.current.set(key, item);
  });

  const drop = useCallback((key: string) => {
    seen.current.delete(key);
    // Ушедший забыт целиком: вернувшись, он появится заново и въедет как новый.
    born.current.delete(key);
    refs.current.delete(key);
    setOrder((previous) => previous.filter((held) => held !== key));
  }, []);

  const leaving = list
    .filter((held) => held.leaving)
    .map((held) => held.key)
    .join(SEPARATOR);

  useEffect(() => {
    const going = new Set(leaving === '' ? [] : leaving.split(SEPARATOR));

    // Вернулся до конца выхода — ожидание снято: движение прерываемо, и узел, открытый
    // снова, не имеет права исчезнуть по концу прошлого закрытия.
    for (const [key, cancel] of holds.current) {
      if (going.has(key)) continue;
      cancel();
      holds.current.delete(key);
    }

    for (const key of going) {
      if (holds.current.has(key)) continue;

      const duration = exitDurationMs();
      if (duration <= 0) {
        drop(key);
        continue;
      }

      // Ожидание записано до того, как началось: движений у узла может не оказаться
      // вовсе, и тогда оно кончается, не успев вернуть отмену.
      let cancel = () => {};
      holds.current.set(key, () => cancel());
      cancel = awaitExit(nodes.current.get(key), duration, () => {
        holds.current.delete(key);
        drop(key);
      });
    }
  }, [leaving, drop]);

  useEffect(() => {
    const pending = holds.current;
    return () => {
      for (const cancel of pending.values()) cancel();
      pending.clear();
    };
  }, []);

  return list;
}
