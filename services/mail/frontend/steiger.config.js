import fsd from '@feature-sliced/steiger-plugin';
import { defineConfig } from 'steiger';

export default defineConfig([
  ...fsd.configs.recommended,
  {
    // На старте проекта слайсы используются в одном месте — это нормально.
    rules: {
      'fsd/insignificant-slice': 'off',
    },
  },
]);
