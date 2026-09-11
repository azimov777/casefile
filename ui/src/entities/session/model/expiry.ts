/**
 * Признак «сохранённый токен перестал годиться».
 *
 * Живёт рядом с сеансом, а не в `app`: поднимает его перехватчик `401` (подписку
 * заводит `app`), а читает экран входа, чтобы объяснить человеку, почему его сюда
 * вернуло. Через адрес страницы это не передать — туда токен и его судьба не попадают.
 */
type Listener = () => void;

const listeners = new Set<Listener>();
let expired = false;

function notify(): void {
  for (const listener of listeners) listener();
}

export function markSessionExpired(): void {
  if (expired) return;
  expired = true;
  notify();
}

/** Забыть отказ: человек вошёл заново или вышел сам. */
export function resetSessionExpiry(): void {
  if (!expired) return;
  expired = false;
  notify();
}

export function subscribeSessionExpiry(listener: Listener): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function getSessionExpired(): boolean {
  return expired;
}
