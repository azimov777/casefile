/**
 * Подписи кирпичей интерфейса: то, что говорит не экран, а сам механизм, — и потому
 * не принадлежит ни одному экрану.
 */
export const ui = {
  language: 'Interface language',
  error: {
    unknown: 'Unknown error.',
    unknownCode: 'Unknown error ({{code}}).',
    // Фраза бэкенда, которую нечем заменить: код называется рядом, чтобы человеку
    // было что процитировать в задаче.
    withCode: '{{message}} ({{code}})',
  },
} as const;
