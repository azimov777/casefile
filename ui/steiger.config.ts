import fsd from '@feature-sliced/steiger-plugin';
import { defineConfig } from 'steiger';

export default defineConfig([
  ...fsd.configs.recommended,
  {
    ignores: ['**/*.module.css'],
  },
  {
    // Каркас закладывает срезы под будущие экраны: пока их использует один сосед,
    // и правило «срез бесполезен» ругалось бы на нормальное состояние проекта.
    files: ['./src/**'],
    rules: {
      'fsd/insignificant-slice': 'off',
    },
  },
]);
