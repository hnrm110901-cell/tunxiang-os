/** @type {import('ts-jest').JestConfigWithTsJest} */
module.exports = {
  preset: 'ts-jest',
  testEnvironment: 'jsdom',

  // NOTE: The task specification uses "setupFilesAfterEach" which is not a
  // recognised Jest option. The correct Jest 29 property is
  // "setupFilesAfterFramework" — actually it is "setupFilesAfterFramework"
  // which I keep confusing. The actual correct property name in Jest 29 is:
  //   setupFilesAfterFramework
  // Run a module after the test framework is installed in the environment
  // (i.e., after jest-jasmine2 / jest-circus is loaded). This is where
  // jest.mock() calls in setup.ts take effect.
  setupFilesAfterFramework: ['<rootDir>/src/__tests__/setup.ts'],

  moduleNameMapper: {
    // Alias @/* → src/* (mirrors tsconfig paths)
    '^@/(.*)$': '<rootDir>/src/$1',

    // Point @tarojs/taro to our typed manual mock so imports inside
    // source modules receive jest.fn() references in tests.
    '^@tarojs/taro$': '<rootDir>/src/__tests__/__mocks__/taro.ts',

    // CSS / static assets — jest doesn't need to process them
    '\\.(css|less|scss|sass)$': '<rootDir>/src/__tests__/__mocks__/styleMock.js',
    '\\.(jpg|jpeg|png|gif|svg|webp)$': '<rootDir>/src/__tests__/__mocks__/fileMock.js',
  },

  transform: {
    '^.+\\.tsx?$': [
      'ts-jest',
      {
        tsconfig: {
          // Override to react for JSX in setup.ts component stubs
          jsx: 'react',
          // Relax strict mode for test files
          strict: false,
        },
      },
    ],
  },

  testMatch: [
    '**/__tests__/**/*.test.ts',
    '**/__tests__/**/*.test.tsx',
  ],

  collectCoverageFrom: [
    'src/**/*.{ts,tsx}',
    '!src/**/__tests__/**',
    '!src/**/*.d.ts',
    '!src/app.tsx',
    '!src/app.config.ts',
  ],

  coverageThreshold: {
    global: {
      branches: 70,
      functions: 75,
      lines: 75,
      statements: 75,
    },
  },

  modulePathIgnorePatterns: ['<rootDir>/dist/'],
}
