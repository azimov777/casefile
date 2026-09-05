import { setupServer } from 'msw/node';

/** Обработчики задаёт каждый тест сам: общего набора «на всё» нет намеренно. */
export const server = setupServer();
