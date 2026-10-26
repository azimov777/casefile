/**
 * Отдаёт байты браузеру сохранением под данным именем: скрытая ссылка с `download`.
 * Ссылка на `blob:` нужна только на время нажатия и отзывается сразу после него.
 */
export function saveBlob(blob: Blob, name: string): void {
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = name;
  link.rel = 'noopener';
  document.body.append(link);
  link.click();
  link.remove();
  // Сохранение начинается синхронно с нажатием; отзыв в следующем такте его не обрывает.
  setTimeout(() => URL.revokeObjectURL(url), 0);
}
