import { HomePage } from '@/pages/home';

import { StoreProvider } from './model/StoreProvider';
import './styles/index.css';

export const App = () => (
  <StoreProvider>
    <HomePage />
  </StoreProvider>
);
