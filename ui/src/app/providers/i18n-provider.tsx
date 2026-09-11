import type { ReactNode } from 'react';
import { I18nextProvider } from 'react-i18next';
import { i18n } from '@/shared/i18n';

/**
 * Язык интерфейса вокруг всего приложения.
 *
 * Экземпляр один на приложение и объявлен провайдером явно, хотя `initReactI18next`
 * умеет отдавать его и без контекста: неявный глобальный экземпляр — ровно то, из-за
 * чего страничный тест начинает зависеть от порядка импортов.
 */
export function I18nProvider({ children }: { children: ReactNode }) {
  return <I18nextProvider i18n={i18n}>{children}</I18nextProvider>;
}
