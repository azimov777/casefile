import { useState } from 'react';
import { RouterProvider, createBrowserRouter } from 'react-router';
import { createQueryClient } from './config/query-client';
import { AppProviders } from './providers/app-providers';
import { routes } from './routes/routes';

export function App() {
  const [queryClient] = useState(createQueryClient);
  const [router] = useState(() => createBrowserRouter(routes));

  return (
    <AppProviders queryClient={queryClient}>
      <RouterProvider router={router} />
    </AppProviders>
  );
}
