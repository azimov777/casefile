import { matchQuery, type QueryCache, type QueryClient } from '@tanstack/react-query';
import { taskKeys } from '@/entities/task';
import { releaseRequested, settleRequested } from './deferred';

/*
 * Чтение таблицы снимает то, что копила полоса (UI-95).
 *
 * Полоса предлагает показать изменения с последнего чтения таблицы, а не с последнего
 * нажатия: таблица перечитывается и мимо полосы — на приходе с доски или из карточки
 * (`staleTime` ноль), на смене отбора и страницы, — и полоса над только что
 * прочитанными строками предлагала бы показать то, что уже показано.
 *
 * Чтение узнаётся в кэше TanStack, а не в строке запроса страницы: кто бы его ни вызвал,
 * оно проходит через одно и то же действие `fetch`, а путь мимо строки запроса
 * (перечитывание по ключу, «Повторить», сброс границы ошибок) иначе ускользнул бы.
 *
 * Время у каждой из трёх точек своё:
 *
 * - **начало** — действие `fetch`. TanStack диспатчит его внутри `Query.fetch` раньше,
 *   чем зовёт функцию запроса, а слушателей кэша будит внутри того же диспатча:
 *   накопленное забирается строго до того, как запрос уходит в сеть;
 * - **ответ лёг** — действие `success`, и других чтений таблицы в пути не осталось:
 *   пока хоть одно идёт, забранное может принадлежать ему, а его ответ ещё не пришёл;
 * - **не лёг** — `error` или откат отменённого чтения: забранное возвращается в полосу
 *   сразу, даже если в пути есть другое чтение. Ошибиться здесь можно только лишним
 *   предложением, а не потерянным кадром.
 */

/** Идёт ли хоть одно чтение таблицы — под любым ключом отбора, в сети или на паузе. */
function tableIsReading(cache: QueryCache): boolean {
  return cache
    .findAll({ queryKey: taskKeys.table })
    .some((query) => query.state.fetchStatus !== 'idle');
}

/**
 * Подписаться на чтения таблицы. Возвращает отписку — для `useEffect`.
 *
 * Поднимается один раз на вкладку рядом с потоком: копит полосу поток, и снимать её
 * должен тот же срез, а не страница, которая может быть не смонтирована, когда ответ
 * ляжет.
 */
export function watchTableReads(queryClient: QueryClient): () => void {
  const cache = queryClient.getQueryCache();

  return cache.subscribe((event) => {
    if (event.type !== 'updated') return;
    if (!matchQuery({ queryKey: taskKeys.table }, event.query)) return;

    const { action } = event;
    switch (action.type) {
      case 'fetch':
        releaseRequested();
        return;
      case 'success':
        // Ручная запись в кэш — не чтение: сервер её не отдавал.
        if (action.manual === true) return;
        if (!tableIsReading(cache)) settleRequested(true);
        return;
      case 'error':
        settleRequested(false);
        return;
      case 'setState':
        // Так TanStack откатывает отменённое чтение: запрос снова свободен, а ответа
        // не было.
        if (event.query.state.fetchStatus === 'idle') settleRequested(false);
        return;
      default:
        return;
    }
  });
}

/**
 * «Показать»: перечитать таблицу по просьбе человека.
 *
 * Накопленное забирается здесь же, до перечитывания, а не только действием `fetch`:
 * если таблица уже читалась, TanStack тихо отменяет старое чтение и заводит новое, не
 * диспатча `fetch` второй раз, — и кадры, пришедшие после начала старого, остались бы
 * в полосе над ответом, который их принёс.
 *
 * Чтения могло и не случиться — запрос таблицы не смонтирован или выключен. Тогда
 * забранное возвращается сразу: ждать исхода чтения, которого нет, значит спрятать
 * кадры, которых строки не видели.
 */
export function readTable(queryClient: QueryClient): void {
  for (const key of releaseRequested()) void queryClient.invalidateQueries({ queryKey: key });
  if (!tableIsReading(queryClient.getQueryCache())) settleRequested(false);
}
