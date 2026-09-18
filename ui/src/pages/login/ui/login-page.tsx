import { useTranslation } from 'react-i18next';
import { Navigate, useNavigate } from 'react-router';
import { useInstallLocked, useSessionExpired, useSessionToken } from '@/entities/session';
import { LoginForm, PasswordForm } from '@/features/auth';
import { LanguageSwitch } from '@/features/switch-language';
import { Callout } from '@/shared/ui';

export function LoginPage() {
  const token = useSessionToken();
  const expired = useSessionExpired();
  // Установка, закрытая паролем владельца, спрашивает пароль, а не токен (`TRK-90`):
  // ключ после входа отдаёт она сама, и токен человеку знать незачем.
  const locked = useInstallLocked();
  const navigate = useNavigate();
  const { t } = useTranslation('login');

  // Вошедшему на экране входа делать нечего.
  if (token !== null) return <Navigate to="/tasks" replace />;

  return (
    /*
     * Карточка прижата к верху (`items-start` плюс верхний отступ), а не центрирована:
     * центрирование по вертикали означает, что каждая появившаяся строка — сообщение
     * об отказе, объяснение просроченного сеанса — двигает вверх всё, включая кнопку,
     * в которую человек целится (замерено: 508 → 477 пикселей). Прижатая сверху карточка
     * растёт только вниз (выявлено при обзоре задачи 01).
     *
     * Отступ задан `clamp`, а не одним шагом сетки: на низком окне карточка не должна
     * уезжать за нижний край, на высоком — стоять под самой кромкой. Края взяты шагами
     * сетки; у доли высоты окна своего токена нет и быть не может.
     */
    <main className="flex min-h-full items-start justify-center px-4 pt-[clamp(calc(var(--spacing)*8),18vh,calc(var(--spacing)*48))] pb-8">
      <div className="flex w-full max-w-112 flex-col gap-6 rounded-control border border-line bg-surface p-8">
        {/*
         * Переключатель языка стоит на самом входе, а не только в оболочке: сюда человек
         * попадает первым делом, и язык ему может понадобиться до того, как он вообще
         * получит право что-то увидеть.
         */}
        <div className="flex items-start justify-between gap-4">
          <div>
            <h1 className="text-title">{t('title')}</h1>
            <p className="mt-1 text-meta text-muted">{locked ? t('passwordIntro') : t('intro')}</p>
          </div>
          {/* Отрицательное поле гасит внутренний отступ кнопки: подпись встаёт по краю
              карточки, а область нажатия остаётся прежней. */}
          <LanguageSwitch className="-mr-2 shrink-0" />
        </div>

        {expired ? (
          <Callout tone="danger">{locked ? t('passwordExpired') : t('expired')}</Callout>
        ) : null}

        {locked ? (
          <PasswordForm onSuccess={() => void navigate('/tasks', { replace: true })} />
        ) : (
          <LoginForm onSuccess={() => void navigate('/tasks', { replace: true })} />
        )}
      </div>
    </main>
  );
}
