/** @type {import('stylelint').Config} */
export default {
  extends: [
    'stylelint-config-standard',
    'stylelint-config-css-modules',
    'stylelint-config-recess-order',
  ],
  ignoreFiles: ['dist/**', 'coverage/**'],
  rules: {
    // CSS Modules: классы в camelCase, чтобы обращаться как styles.myClass
    'selector-class-pattern': [
      '^[a-z][a-zA-Z0-9]*$',
      { message: 'Используйте camelCase для имён классов (CSS Modules)' },
    ],
    'custom-property-pattern': [
      '^[a-z][a-z0-9]*(-[a-z0-9]+)*$',
      { message: 'Используйте kebab-case для CSS-переменных' },
    ],
  },
};
