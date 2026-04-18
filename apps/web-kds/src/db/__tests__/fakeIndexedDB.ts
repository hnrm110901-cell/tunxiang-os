/**
 * 极简 IndexedDB in-memory shim — 仅供 vitest/jsdom 测试使用。
 * 覆盖面：open / createObjectStore / createIndex / put / get / getAll / delete / clear
 *         事务 readonly/readwrite / onsuccess / onerror / oncomplete
 * 不实现：游标、版本冲突、真实并发锁。够 kdsOrdersDB 的读写测试用。
 */

type AnyRecord = Record<string, unknown>;

interface Store {
  keyPath: string;
  data: Map<string, AnyRecord>;
  indexes: Set<string>;
}

interface Database {
  name: string;
  version: number;
  stores: Map<string, Store>;
}

const databases = new Map<string, Database>();
let disabled = false;

class FakeIDBRequest<T = unknown> {
  result: T | undefined;
  error: DOMException | null = null;
  onsuccess: ((this: FakeIDBRequest<T>, ev: Event) => unknown) | null = null;
  onerror: ((this: FakeIDBRequest<T>, ev: Event) => unknown) | null = null;
  onupgradeneeded: ((this: FakeIDBRequest<T>, ev: Event) => unknown) | null = null;

  _fireSuccess(result: T): void {
    this.result = result;
    queueMicrotask(() => {
      if (this.onsuccess) this.onsuccess.call(this, new Event('success'));
    });
  }

  _fireError(err: DOMException): void {
    this.error = err;
    queueMicrotask(() => {
      if (this.onerror) this.onerror.call(this, new Event('error'));
    });
  }
}

class FakeIDBObjectStore {
  constructor(public store: Store, private tx: FakeIDBTransaction) {}

  put(record: AnyRecord): FakeIDBRequest {
    const req = new FakeIDBRequest();
    this.tx._enqueue(() => {
      const key = record[this.store.keyPath] as string;
      this.store.data.set(key, record);
      req._fireSuccess(key);
    });
    return req;
  }

  get(key: string): FakeIDBRequest<AnyRecord | undefined> {
    const req = new FakeIDBRequest<AnyRecord | undefined>();
    this.tx._enqueue(() => req._fireSuccess(this.store.data.get(key)));
    return req;
  }

  getAll(): FakeIDBRequest<AnyRecord[]> {
    const req = new FakeIDBRequest<AnyRecord[]>();
    this.tx._enqueue(() => req._fireSuccess(Array.from(this.store.data.values())));
    return req;
  }

  delete(key: string): FakeIDBRequest {
    const req = new FakeIDBRequest();
    this.tx._enqueue(() => {
      this.store.data.delete(key);
      req._fireSuccess(undefined);
    });
    return req;
  }

  clear(): FakeIDBRequest {
    const req = new FakeIDBRequest();
    this.tx._enqueue(() => {
      this.store.data.clear();
      req._fireSuccess(undefined);
    });
    return req;
  }

  createIndex(name: string, _keyPath: string, _opts?: IDBIndexParameters): void {
    this.store.indexes.add(name);
  }

  count(): FakeIDBRequest<number> {
    const req = new FakeIDBRequest<number>();
    this.tx._enqueue(() => req._fireSuccess(this.store.data.size));
    return req;
  }
}

class FakeIDBTransaction {
  oncomplete: ((ev: Event) => unknown) | null = null;
  onerror: ((ev: Event) => unknown) | null = null;
  private ops: Array<() => void> = [];
  private done = false;

  constructor(private db: FakeIDBDatabase, _storeNames: string[]) {
    queueMicrotask(() => this._flush());
  }

  objectStore(name: string): FakeIDBObjectStore {
    const store = this.db._getStore(name);
    if (!store) throw new Error(`No store ${name}`);
    return new FakeIDBObjectStore(store, this);
  }

  _enqueue(fn: () => void): void {
    this.ops.push(fn);
  }

  _flush(): void {
    if (this.done) return;
    this.done = true;
    try {
      for (const op of this.ops) op();
      if (this.oncomplete) this.oncomplete(new Event('complete'));
    } catch (err) {
      if (this.onerror) this.onerror(new Event('error'));
      throw err;
    }
  }
}

class FakeIDBDatabase {
  constructor(private db: Database) {}

  get name(): string { return this.db.name; }
  get version(): number { return this.db.version; }
  get objectStoreNames(): { contains(name: string): boolean } {
    return { contains: (n: string) => this.db.stores.has(n) };
  }

  createObjectStore(name: string, opts: { keyPath: string }): FakeIDBObjectStore {
    const store: Store = { keyPath: opts.keyPath, data: new Map(), indexes: new Set() };
    this.db.stores.set(name, store);
    const tempTx = new FakeIDBTransaction(this, [name]);
    return new FakeIDBObjectStore(store, tempTx);
  }

  transaction(storeNames: string | string[], _mode?: 'readonly' | 'readwrite'): FakeIDBTransaction {
    const names = Array.isArray(storeNames) ? storeNames : [storeNames];
    return new FakeIDBTransaction(this, names);
  }

  close(): void { /* no-op */ }

  _getStore(name: string): Store | undefined {
    return this.db.stores.get(name);
  }
}

const fakeIndexedDB = {
  open(name: string, version: number): FakeIDBRequest<FakeIDBDatabase> {
    const req = new FakeIDBRequest<FakeIDBDatabase>();
    if (disabled) {
      queueMicrotask(() => req._fireError(new DOMException('disabled', 'UnknownError')));
      return req;
    }
    let db = databases.get(name);
    const isNew = !db || (db && db.version < version);
    if (!db) {
      db = { name, version, stores: new Map() };
      databases.set(name, db);
    } else if (db.version < version) {
      db.version = version;
    }
    const fakeDb = new FakeIDBDatabase(db);
    if (isNew) {
      queueMicrotask(() => {
        if (req.onupgradeneeded) {
          req.result = fakeDb;
          req.onupgradeneeded.call(req, new Event('upgradeneeded'));
        }
        req._fireSuccess(fakeDb);
      });
    } else {
      req._fireSuccess(fakeDb);
    }
    return req;
  },
  deleteDatabase(name: string): FakeIDBRequest {
    const req = new FakeIDBRequest();
    databases.delete(name);
    queueMicrotask(() => req._fireSuccess(undefined));
    return req;
  },
};

export function installFakeIndexedDB(): void {
  (globalThis as unknown as { indexedDB: typeof fakeIndexedDB }).indexedDB = fakeIndexedDB;
}

export function resetFakeIndexedDB(): void {
  databases.clear();
  disabled = false;
}

export function disableFakeIndexedDB(): void {
  disabled = true;
  databases.clear();
  delete (globalThis as unknown as { indexedDB?: unknown }).indexedDB;
}

export function restoreFakeIndexedDB(): void {
  disabled = false;
  installFakeIndexedDB();
}
