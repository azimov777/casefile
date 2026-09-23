/**
 * Сохраняет значение как файл `.json` через диалог браузера «Сохранить как».
 *
 * Ссылки `<a download>` хватает: у архива нет второго формата и второго пути показать
 * его человеку, поэтому отдельная библиотека загрузки файлов не берётся. Узел ссылки
 * никогда не попадает в разметку — он создаётся, кликается и уничтожается одним ходом.
 */
export function saveJsonFile(value: unknown, filename: string): void {
  const blob = new Blob([JSON.stringify(value, null, 2)], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  try {
    const link = document.createElement('a');
    link.href = url;
    link.download = filename;
    link.click();
  } finally {
    // Отложено: некоторые браузеры читают `href` асинхронно после `click()`, и немедленный
    // `revokeObjectURL` изредка обрывал загрузку раньше, чем она началась.
    setTimeout(() => URL.revokeObjectURL(url), 0);
  }
}

/**
 * Имя файла архива: `casefile-archive-<дата>.json`, дата — календарный день выгрузки
 * в часовом поясе браузера. Секунды в имени не нужны — двух выгрузок в один день из
 * одного браузера не различить и по остальным полям файла незачем.
 */
export function archiveFilename(exportedAt: Date = new Date()): string {
  const year = exportedAt.getFullYear();
  const month = String(exportedAt.getMonth() + 1).padStart(2, '0');
  const day = String(exportedAt.getDate()).padStart(2, '0');
  return `casefile-archive-${year}-${month}-${day}.json`;
}
