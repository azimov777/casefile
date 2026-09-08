import { Component, type ErrorInfo, type ReactNode } from 'react';
import { Button } from '@/shared/ui';

interface ErrorBoundaryProps {
  children: ReactNode;
}

interface ErrorBoundaryState {
  failed: boolean;
}

/**
 * Граница ошибок: падение отрисовки не должно оставлять человека перед белым экраном.
 *
 * Классовый компонент — не выбор стиля: перехват ошибки отрисовки в React делается
 * только `getDerivedStateFromError` и `componentDidCatch`, у хуков такого нет.
 *
 * Отказы запросов сюда не приходят и приходить не должны: у них своё состояние
 * (`QueryState`) с повтором. Здесь остаётся то, что чинится только перезагрузкой.
 */
export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  override state: ErrorBoundaryState = { failed: false };

  static getDerivedStateFromError(): ErrorBoundaryState {
    return { failed: true };
  }

  override componentDidCatch(error: Error, info: ErrorInfo) {
    // Человеку — что случилось и что делать, разработчику — трасса. Показывать
    // сообщение исключения на странице бессмысленно: оно на английском и про наш код.
    console.error('Отрисовка упала:', error, info.componentStack);
  }

  override render() {
    if (!this.state.failed) return this.props.children;

    return (
      <div
        role="alert"
        className="mx-auto my-8 flex max-w-168 flex-col items-start gap-3 rounded-control border border-danger-line bg-danger-soft p-6"
      >
        <h1 className="text-title text-danger">Интерфейс сломался на этом месте</h1>
        {/* Тоном отказа окрашен только заголовок: объяснение — обычный текст, и цвет
            содержания на цветной заливке назван явно, чтобы он не унаследовал тон. */}
        <p className="text-text">
          Экран не отрисовался из-за ошибки в самом интерфейсе — данные тут ни при чём. Подробности
          ошибки лежат в консоли браузера.
        </p>
        <Button onClick={() => window.location.reload()}>Перезагрузить</Button>
      </div>
    );
  }
}
