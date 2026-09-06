import '@testing-library/jest-dom/vitest';
import { afterAll, afterEach, beforeAll } from 'vitest';
import { resetSessionExpiry } from '@/entities/session';
import { clearToken } from '@/shared/api';
// Импортируется после подмены потока и точечно, минуя вход среза: вход тянет за собой
// клиент SSE, а он в этот момент ещё не подменён — и настоящий в jsdom не работает.
import { liveJournal } from './live-journal';
import { resetDeferred } from '@/features/live-journal/model/deferred';
import { server } from './msw/server';

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
  resetSessionExpiry();
  // Черновики ответов живут в `sessionStorage` и переживают перерисовку намеренно —
  // а значит переживут и тест: без уборки следующий тест начинается с чужим текстом
  // в поле, и падает он не там, где ошибка.
  window.sessionStorage.clear();
  window.localStorage.clear();
  liveJournal.reset();
  // Отложенные обновления списка живут в модуле, а не в React: без уборки следующий
  // тест начинается с чужой полосой «изменилось задач: N».
  resetDeferred();
});

afterAll(() => {
  server.close();
});
