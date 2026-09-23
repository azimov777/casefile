import '@testing-library/jest-dom/vitest';
import { afterAll, afterEach, beforeAll } from 'vitest';
import { resetSessionExpiry } from '@/entities/session';
import { clearToken } from '@/shared/api';
// Точечно, минуя вход сегмента: снаружи этой двери нет — прочитанная конфигурация
// установки живёт в модуле и переживает тест, а «забыть» её нужно только оснастке.
import { resetInstallConfig } from '@/shared/api/install-config';
// Импортируется после подмены потока и точечно, минуя вход среза: вход тянет за собой
// клиент SSE, а он в этот момент ещё не подменён — и настоящий в jsdom не работает.
import { liveJournal } from './live-journal';
import { resetIntersection, installIntersection } from './intersection';
import { resetDeferred } from '@/features/live-journal/model/deferred';
import { server } from './msw/server';

/*
 * Чего нет в jsdom, но что зовут компоненты Radix: захват указателя и прокрутка
 * элемента в вид. Без заглушек клик по их триггеру падает
 * `target.hasPointerCapture is not a function` — падает среда, а не поведение.
 *
 * Заглушки чинят падение, но не дают поведения: открыть список Radix в jsdom всё
 * равно нельзя (проверено — см. `docs/notes/testing.md`). Ходьбу стрелками, `Esc`,
 * возврат фокуса и сам выбор значения проверяет сквозной тест в настоящем браузере.
 */
Element.prototype.hasPointerCapture ??= () => false;
Element.prototype.setPointerCapture ??= () => {};
Element.prototype.releasePointerCapture ??= () => {};
Element.prototype.scrollIntoView ??= () => {};

/*
 * `Blob.prototype.text` и `URL.createObjectURL`/`revokeObjectURL` в jsdom нет, а на
 * них стоит выбор и сохранение файла архива установки (`features/manage-installation`):
 * `file.text()` разбирает выбранный файл, `createObjectURL` даёт ссылку на скачивание.
 * Заглушка чинит падение среды, а не даёт настоящей загрузки файла — читает выбранный
 * файл через `FileReader` (в jsdom он есть по-настоящему), а адрес объекта не более
 * чем строка-плейсхолдер: что с ней делает код, проверяет сам тест.
 */
Blob.prototype.text ??= function (this: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result));
    reader.onerror = () => reject(reader.error as Error);
    reader.readAsText(this);
  });
};
URL.createObjectURL ??= () => 'blob:jsdom-stub';
URL.revokeObjectURL ??= () => {};

/*
 * `ResizeObserver` в jsdom нет вовсе, а доска задач считает им свою высоту: она
 * пересчитывается, когда над ней вырастает раскрытая форма отбора
 * (`src/pages/tasks/ui/tasks-board.tsx`). Заглушка чинит падение среды, а не даёт
 * поведения: без раскладки в jsdom мерить всё равно нечего — высоту доски и то,
 * что страница под ней не прокручивается, проверяет `e2e/board.spec.ts`.
 */
globalThis.ResizeObserver ??= class {
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
};

/*
 * `IntersectionObserver` в jsdom тоже нет, а столбец доски дочитывается им по мере
 * прокрутки (`src/shared/lib/end-reach.ts`). Здесь он не заглушка, а управляемый:
 * геометрии в jsdom нет, и «сторож показался» тест говорит сам (`reachEnd`).
 */
installIntersection();

// Подмена API поднимается на весь прогон: тест, который сходил в сеть мимо обработчика,
// должен падать, а не тихо получать чужой ответ.
beforeAll(() => {
  server.listen({ onUnhandledRequest: 'error' });
});

afterEach(() => {
  server.resetHandlers();
  // Токен и признак просроченного сеанса живут в модулях, а не в React: чистить
  // одно хранилище мало — копия в памяти пережила бы тест.
  clearToken();
  resetInstallConfig();
  resetSessionExpiry();
  // Черновики ответов живут в `sessionStorage` и переживают перерисовку намеренно —
  // а значит переживут и тест: без уборки следующий тест начинается с чужим текстом
  // в поле, и падает он не там, где ошибка.
  window.sessionStorage.clear();
  window.localStorage.clear();
  liveJournal.reset();
  // Наблюдатели пересечения живут в модуле: без уборки следующий тест начинается
  // со сторожами, стоящими на узлах снятой страницы.
  resetIntersection();
  // Отложенные обновления списка живут в модуле, а не в React: без уборки следующий
  // тест начинается с чужой полосой «изменилось задач: N».
  resetDeferred();
});

afterAll(() => {
  server.close();
});
