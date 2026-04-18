import '@testing-library/jest-dom/vitest';
import { afterEach, vi } from 'vitest';
import { cleanup } from '@testing-library/react';
import { installFakeIndexedDB, resetFakeIndexedDB } from './db/__tests__/fakeIndexedDB';

installFakeIndexedDB();

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.useRealTimers();
  resetFakeIndexedDB();
});
