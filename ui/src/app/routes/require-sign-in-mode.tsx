import { Outlet } from 'react-router';
import { useInstallLocked } from '@/entities/session';
import { NotFound } from './not-found';

/**
 * Экраны, которые есть только в режиме входа по учётным записям: своя учётная запись и
 * люди установки (`TRK-113`).
 *
 * На своей машине их нет вовсе — ни пункта в панели, ни адреса: человек там один, пароля
 * у него нет, и заводить некого (решение владельца, `TRK-91#39`). Прямая ссылка ведёт
 * на «страницу не найдено», а не на форму, которая ответила бы отказом.
 */
export function RequireSignInMode() {
  const signIn = useInstallLocked();
  return signIn ? <Outlet /> : <NotFound />;
}
