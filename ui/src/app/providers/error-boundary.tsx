import { Component, type ErrorInfo, type ReactNode } from 'react';
import { BrokenScreen } from './broken-screen';

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
    console.error('Render failed:', error, info.componentStack);
  }

  override render() {
    if (!this.state.failed) return this.props.children;
    return <BrokenScreen />;
  }
}
