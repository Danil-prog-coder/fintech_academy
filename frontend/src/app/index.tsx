import { RouterProvider } from 'react-router';

import { StoreProvider } from './model/StoreProvider';
import { router } from './routes/router';
import './styles/index.css';

export const App = () => (
  <StoreProvider>
    <RouterProvider router={router} />
  </StoreProvider>
);
