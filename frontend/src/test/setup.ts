import '@testing-library/jest-dom/vitest';

import { notifications } from '@mantine/notifications';
import { cleanup } from '@testing-library/react';
import { setupServer } from 'msw/node';
import { afterAll, afterEach, beforeAll, beforeEach } from 'vitest';

import { handlers, resetDb } from './handlers';

// jsdom lacks these; Mantine needs them.
Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: (query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  }),
});
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
window.ResizeObserver = ResizeObserverStub;
window.HTMLElement.prototype.scrollIntoView = () => {};

// Newer Node versions ship a global localStorage that shadows jsdom's and is unusable
// without --localstorage-file; use a simple in-memory one for every test.
class MemoryStorage implements Storage {
  private data = new Map<string, string>();
  get length() {
    return this.data.size;
  }
  clear() {
    this.data.clear();
  }
  getItem(key: string) {
    return this.data.get(key) ?? null;
  }
  key(index: number) {
    return [...this.data.keys()][index] ?? null;
  }
  removeItem(key: string) {
    this.data.delete(key);
  }
  setItem(key: string, value: string) {
    this.data.set(key, String(value));
  }
}
for (const target of [globalThis, window]) {
  Object.defineProperty(target, 'localStorage', { value: new MemoryStorage(), configurable: true });
}

export const server = setupServer(...handlers);

beforeAll(() => {
  server.listen({ onUnhandledRequest: 'error' });
  // Node's fetch (which MSW wraps on listen) rejects jsdom's AbortSignal ("Expected signal
  // to be an instance of AbortSignal"). Tests never rely on aborting, so drop the signal.
  const mockedFetch = globalThis.fetch;
  globalThis.fetch = (input, init) => mockedFetch(input, init && { ...init, signal: undefined });
});
beforeEach(() => resetDb());
afterEach(() => {
  cleanup();
  // The notifications store is global: without this, earlier tests' toasts fill the visible
  // limit and later ones wait in a queue.
  notifications.clean();
  notifications.cleanQueue();
  server.resetHandlers();
});
afterAll(() => server.close());
