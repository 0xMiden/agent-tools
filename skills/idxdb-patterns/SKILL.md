---
name: idxdb-patterns
description: Enforce conventions for the IndexedDB/Dexie persistence layer of the Miden web client, which lives in the web-sdk repo (idxdb-store crate). Use when editing TypeScript in `crates/idxdb-store/src/ts/`, writing Dexie transactions, or modifying the database schema.
---

# IndexedDB Store Patterns (idxdb-store)

This layer lives in the **web-sdk** repo (`github.com/0xMiden/web-sdk`,
crate `crates/idxdb-store`, package `miden-idxdb-store`), not in the
`miden-client` repo. It is a Dexie-backed `Store` implementation for the
WASM web client.

The schema splits account-related tables into `Latest…` / `Historical…`
pairs to support account-history pruning. Always check
`crates/idxdb-store/src/ts/schema.ts` for the canonical table list before
adding rows or filters. The full set, in declaration order, is:
`AccountCode`, `LatestAccountStorage`, `HistoricalAccountStorage`,
`LatestAccountAssets`, `HistoricalAccountAssets`, `LatestStorageMapEntries`,
`HistoricalStorageMapEntries`, `AccountAuth`, `AccountKeyMapping`,
`LatestAccountHeaders`, `HistoricalAccountHeaders`, `Addresses`,
`Transactions`, `TransactionScripts`, `InputNotes`, `OutputNotes`,
`NotesScripts`, `BlockchainCheckpoint`, `BlockHeaders`,
`PartialBlockchainNodes`, `Tags`, `ForeignAccountCode`, `Settings`.

## Build Workflow

The `idxdb-store` has a dual-file workflow:

- **TypeScript source** lives in `crates/idxdb-store/src/ts/`
- **Generated JavaScript** lives in `crates/idxdb-store/src/js/`
- **Both are committed to git** — the `js` folder is currently *not*
  gitignored (the `#js` entry in `src/.gitignore` is commented out)
- The Rust side imports the generated `.js` modules via
  `#[wasm_bindgen(module = "/src/js/...")]`, so the JS must be kept in
  sync with the TS

After modifying any `.ts` file, regenerate the JS with the canonical
top-level Make target (which runs the package's `build` script through
**pnpm** — this repo is pnpm-only, there is no yarn):

```bash
make rust-client-ts-build   # == pnpm --filter web_store run build
make rust-client-ts-lint    # == pnpm --filter web_store run lint
make test-idxdb-store       # == pnpm --filter web_store exec vitest run --coverage
```

The underlying package script is `tsc --build --force ./tsconfig.json`
(`crates/idxdb-store/src/package.json`). Always commit both the `.ts`
source and the regenerated `.js` output together.

## Database Registry

There is no JS object pointer on the Rust side, so open databases are
tracked in a module-level `Map` keyed by network name, in
`crates/idxdb-store/src/ts/schema.ts`:

```typescript
const databaseRegistry = new Map<string, MidenDatabase>();

export function getDatabase(dbId: string): MidenDatabase {
  const db = databaseRegistry.get(dbId);
  if (!db) {
    throw new Error(
      `Database not found for id: ${dbId}. Call openDatabase first.`
    );
  }
  return db;
}

export async function openDatabase(
  network: string,
  clientVersion: string
): Promise<string> {
  const db = new MidenDatabase(network);
  const success = await db.open(clientVersion);
  if (!success) {
    throw new Error(`Failed to open IndexedDB database: ${network}`);
  }
  databaseRegistry.set(network, db);
  return network;
}
```

Rules:
- Every exported store function takes `dbId: string` as its first parameter
- Call `const db = getDatabase(dbId)` at the top of each function — look it
  up per call rather than holding a long-lived reference across calls
- The `dbId` is the network name (`"mainnet"`, `"devnet"`, `"testnet"`, or
  a custom one); `openDatabase` registers under and returns `network`

## Schema Interfaces

Define TypeScript interfaces for each table with the `I` prefix. Use
`Latest…` / `Historical…` pairs for anything that participates in account
history (storage slots, storage map entries, vault assets, and account
headers). The account-header pair uses `IAccount` (latest, keyed on `id`)
and `IHistoricalAccount` (same fields plus `replacedAtNonce`) inside
`latestAccountHeaders` / `historicalAccountHeaders`:

```typescript
export interface IAccountCode {
  root: string;
  code: Uint8Array;
}

export interface ILatestAccountStorage {
  accountId: string;
  slotName: string;
  slotValue: string;
  slotType: number;
}

export interface IHistoricalAccountStorage {
  accountId: string;
  replacedAtNonce: string;
  slotName: string;
  oldSlotValue: string | null;
  slotType: number;
}

export interface ILatestAccountAsset {
  accountId: string;
  vaultKey: string;     // holds the asset's AssetId — see below
  asset: string;        // the encoded asset
}

export interface IHistoricalAccountAsset {
  accountId: string;
  replacedAtNonce: string;
  vaultKey: string;
  oldAsset: string | null;
}

export interface IAccount {
  id: string;           // primary key — NOT `accountId`
  codeRoot: string;
  storageRoot: string;
  vaultRoot: string;
  nonce: string;
  committed: boolean;
  accountSeed?: Uint8Array;
  accountCommitment: string;
  locked: boolean;
  watched: boolean;
}
```

The single chain-progress row is `IBlockchainCheckpoint`. There is no
`stateSync` table and no `IStateSync` interface:

```typescript
export interface IBlockchainCheckpoint {
  id: number;
  blockNum: number;
  partialBlockchainPeaks: Uint8Array;
}
```

Dexie's `populate` hook seeds it once, on first database creation only:
`{ id: 1, blockNum: 0, partialBlockchainPeaks: new Uint8Array() }`.
The MMR peaks live on this row, **not** on the tip block header —
`IBlockHeader` is only `{ blockNum, header, hasClientNotes }`. A sync
therefore writes the header and the peaks to two different tables inside
one transaction (`crates/idxdb-store/src/ts/sync.ts`).

Rules:
- Use `string` for hex-encoded values (hashes, IDs, commitments, nonces,
  vault keys)
- Use `Uint8Array` for raw binary data
- Use `?` suffix for optional fields, `| null` when the column explicitly
  represents the absence of a previous value (e.g. `oldSlotValue`,
  `oldAsset`, `oldValue` in the history tables)
- Use `boolean` for flags, `number` for block heights and slot types
- The LATEST account-header table keys on `&id` (with `accountCommitment`
  as a secondary index); the HISTORICAL account-header table keys on
  `&accountCommitment` (with `id` and `[id+replacedAtNonce]` as secondary
  indexes). The `&` marks a unique index. Of the rest, only
  `foreignAccountCode` is keyed on `accountId` alone; the storage, asset and
  map-entry tables use **compound** primary keys with `accountId` merely as a
  secondary index — `[accountId+slotName]`, `[accountId+vaultKey]` and
  `[accountId+slotName+key]` respectively. Don't confuse the two.
- The asset layer is two-column: `vaultKey` holds the asset's **`AssetId`**
  (`crates/idxdb-store/src/account/js_bindings.rs` writes
  `asset.id().to_string()`, and removals write `asset_id.to_string()` from
  `patch.vault().removed_asset_ids()` in
  `crates/idxdb-store/src/account/utils.rs`), while `asset` holds the
  encoded asset. The column name `vaultKey` is legacy and was deliberately
  **not** renamed, so a blind find-replace over it is wrong.

## Table Enum

Define tables as a TypeScript enum, in the order they appear in
`crates/idxdb-store/src/ts/schema.ts` — the Rust side imports table-backed
JS functions verbatim:

```typescript
enum Table {
  AccountCode = "accountCode",
  LatestAccountStorage = "latestAccountStorage",
  HistoricalAccountStorage = "historicalAccountStorage",
  LatestAccountAssets = "latestAccountAssets",
  HistoricalAccountAssets = "historicalAccountAssets",
  LatestStorageMapEntries = "latestStorageMapEntries",
  HistoricalStorageMapEntries = "historicalStorageMapEntries",
  AccountAuth = "accountAuth",
  AccountKeyMapping = "accountKeyMapping",
  LatestAccountHeaders = "latestAccountHeaders",
  HistoricalAccountHeaders = "historicalAccountHeaders",
  Addresses = "addresses",
  Transactions = "transactions",
  TransactionScripts = "transactionScripts",
  InputNotes = "inputNotes",
  OutputNotes = "outputNotes",
  NotesScripts = "notesScripts",
  BlockchainCheckpoint = "blockchainCheckpoint",
  BlockHeaders = "blockHeaders",
  PartialBlockchainNodes = "partialBlockchainNodes",
  Tags = "tags",
  ForeignAccountCode = "foreignAccountCode",
  Settings = "settings",
}
```

## Schema Versioning and Migrations

The `MidenDatabase` constructor holds a **chain of Dexie version blocks**,
not a single one:

```typescript
this.dexie.version(1).stores(V1_STORES);

// v2: data-only fix — no index changes, so .stores({}) is empty.
this.dexie
  .version(2)
  .stores({})
  .upgrade(async (tx) => { /* prune leaked note tags */ });

// v3: replace the input-note consumption index's noteId suffix with detailsCommitment.
this.dexie.version(3).stores({
  [Table.InputNotes]: indexes(
    "detailsCommitment",
    "noteId",
    "nullifier",
    "scriptRoot",
    "stateDiscriminant",
    "[consumedBlockHeight+consumedTxOrder+detailsCommitment]"
  ),
});

// v4/v5: replace settings so it can use the new compound primary key.
this.dexie.version(4).stores({ [Table.Settings]: null });
this.dexie.version(5).stores({
  [Table.Settings]: indexes("[scope+key]", "scope"),
});
```

`V1_STORES` is the **frozen** baseline. Its in-file comment says exactly:
"Version blocks exist below, so V1_STORES is frozen — never modify it;
add a new version block instead." Index strings are built with a small
`indexes(...)` helper, e.g.
`[Table.LatestAccountStorage]: indexes("[accountId+slotName]", "accountId")`.

Migrations coexist with a separate client-version reset. `ensureClientVersion`
closes / `delete`s / re-opens the database when the running client version is
a higher **major or minor** than the stored one; same-major.minor patch bumps
and downgrades just persist the new version (the `sameMajorMinor` /
`!semver.gt(...)` guard). An empty `clientVersion` skips enforcement
entirely, and an unparseable semver on either side forces a reset. The
client version is `CLIENT_VERSION = env!("CARGO_PKG_VERSION")` in
`crates/idxdb-store/src/lib.rs`, persisted under the exported
`CLIENT_VERSION_SETTING_KEY = "clientVersion"`.

**Consequence to state up front in any upgrade plan:** because a minor
client-version bump triggers the reset, shipping an app across a minor SDK
version destroys every locally-stored account, key and note in the user's
browser. Dexie version blocks only cover stores that survive patch upgrades.

Adding a table or changing an index therefore means:
1. Update the `Table` enum + interface(s) in `schema.ts`
2. Add a new `.version(N+1).stores({…}).upgrade(tx => {…})` block. List
   only the tables whose indexes changed — Dexie carries the rest forward.
   Set a table to `null` to remove it. Index-only changes may omit
   `.upgrade()`. **Never modify `V1_STORES` or any previous version block.**
   Note that `populate` fires only on first creation, never during upgrades.
3. Update Rust-side reads/writes, which import the corresponding JS
   functions through `#[wasm_bindgen(module = "/src/js/<file>.js")]`
   (e.g. account functions from `/src/js/accounts.js`, schema/registry
   functions from `/src/js/schema.js`, sync functions from `/src/js/sync.js`)
4. Run `make rust-client-ts-build` to regenerate the JS, and add a
   schema/migration test in `schema.test.ts`

## Dexie Transactions

### Atomic Operations

When multiple tables must be updated together, wrap in a Dexie transaction.
List every table the transaction touches, and use `Promise.all()` to run
independent operations concurrently (from `applyStateSync` in
`crates/idxdb-store/src/ts/sync.ts`):

```typescript
const tablesToAccess = [
  db.blockchainCheckpoint,
  db.inputNotes,
  db.outputNotes,
  db.notesScripts,
  db.transactions,
  db.transactionScripts,
  db.blockHeaders,
  db.partialBlockchainNodes,
  db.tags,
  db.latestAccountHeaders,
  db.historicalAccountHeaders,
  db.latestAccountStorages,
  db.historicalAccountStorages,
  db.latestStorageMapEntries,
  db.historicalStorageMapEntries,
  db.latestAccountAssets,
  db.historicalAccountAssets,
];

return await db.dexie.transaction("rw", tablesToAccess, async (tx) => {
  await Promise.all([
    /* input/output note upserts */,
    /* transaction upserts */,
    /* per-account applyFullAccountState calls */,
    updateSyncHeight(tx, blockNum, newPeaks),
    updatePartialBlockchainNodes(tx, serializedNodeIds, serializedNodes),
    updateCommittedNoteTags(tx, committedNoteTagSources),
    /* block-header writes */,
  ]);
});
```

Rules:
- Use `"rw"` for read-write transactions
- List all tables that will be accessed in the `tablesToAccess` array
- Use `Promise.all()` inside transactions to parallelize independent operations
- Pass the `tx` transaction object to helper functions that need table access
- Helper write functions (e.g. `upsertInputNote`) commonly take an optional
  `tx?: Transaction`: if supplied they run inside the caller's transaction,
  otherwise they open their own `db.dexie.transaction(...)`

### Table Access Within Transactions

The Dexie `Transaction` type doesn't statically declare table accessors.
`schema.ts` augments `declare module "dexie"` so `tx.inputNotes` etc.
type-check; where that augmentation isn't in scope, type-cast the
transaction. Peaks travel with the block number on the same checkpoint row,
so a skipped height update deliberately skips the peaks update too (from
`updateSyncHeight` in `sync.ts`):

```typescript
async function updateSyncHeight(
  tx: Transaction,
  blockNum: number,
  newPeaks: Uint8Array
) {
  try {
    const current = await (
      tx as Transaction & {
        blockchainCheckpoint: Dexie.Table<IBlockchainCheckpoint, number>;
      }
    ).blockchainCheckpoint.get(1);
    if (!current || current.blockNum < blockNum) {
      await (
        tx as Transaction & {
          blockchainCheckpoint: Dexie.Table<IBlockchainCheckpoint, number>;
        }
      ).blockchainCheckpoint.update(1, {
        blockNum: blockNum,
        partialBlockchainPeaks: newPeaks,
      });
    }
  } catch (error) {
    logWebStoreError(error, "Failed to update sync height");
  }
}
```

Read the peaks back through the exported `getCurrentBlockchainPeaks(dbId)`
in `sync.ts` (bound Rust-side as
`#[wasm_bindgen(js_name = getCurrentBlockchainPeaks)]` in
`crates/idxdb-store/src/sync/js_bindings.rs`), which returns
`{ blockNum, peaks }` with `peaks` base64-encoded.

### Forward-Only Updates

Only advance the sync height forward (never regress):

```typescript
if (!current || current.blockNum < blockNum) {
  // Update
}
```

### Never overwrite MMR authentication nodes

`partialBlockchainNodes` values are immutable once written: an index's node
value is fixed, so a differing later write signals a buggy or malicious sync
path. Never call `put` on that table. Use
`putPartialBlockchainNodesNoOverwrite(table, data)` from `./utils.js`, which
dedups the batch, `bulkGet`s the existing rows, `bulkAdd`s only the missing
indices, accepts writes that match the stored value, and **throws** when an
existing index would receive a different value.

### Columns added after the fact

Rows written before a column existed simply lack the property, and a Dexie
`where` equality against `""` never matches them. Filter in JS instead. From
`removeNoteTag` in `sync.ts`, for the `ITag.sourceSubscriptionKey` column:

```typescript
return await db.tags
  .where({ tag: tagBase64, sourceNoteId, sourceAccountId })
  .and((record) => (record.sourceSubscriptionKey ?? "") == subscriptionKey)
  .delete();
```

## Error Handling

### logWebStoreError

Use `logWebStoreError()` from `./utils.js` for error logging — it formats
Dexie errors (and walks `error.inner`), then **re-throws** the error:

```typescript
import { logWebStoreError } from "./utils.js";

try {
  // database operation
} catch (error) {
  logWebStoreError(error, "Error while fetching account headers");
}
```

Because `logWebStoreError` always re-throws, code after a `catch` that
calls it (e.g. a trailing `return []`) is effectively unreachable on the
error path — the surrounding `try` body must return the success value.

Functions with a non-optional return type still need an explicit
`throw error;` after the `logWebStoreError` call so the compiler can see
that no path returns `undefined` (e.g. `removeAccountAddress` in
`accounts.ts`, `removeSetting` in `settings.ts`, both of which return
`Promise<boolean>` derived from Dexie's `Collection.delete()` count).

### Reads return optional / empty

Read functions wrap their body in `try/catch`, returning the queried value
on success. The fallback after the catch (empty array, `null`, or
`undefined`) documents intent but is unreachable because `logWebStoreError`
re-throws (from `getAccountIds` in `crates/idxdb-store/src/ts/accounts.ts`):

```typescript
export async function getAccountIds(dbId: string) {
  try {
    const db = getDatabase(dbId);
    const records = await db.latestAccountHeaders.toArray();
    return records.map((entry) => entry.id);   // header rows key on `id`
  } catch (error) {
    logWebStoreError(error, "Error while fetching account IDs");
  }
  return [];
}
```

## Data Operations

### Querying

Use Dexie's query API. Patterns actually used in the store:

```typescript
// Get all records
const records = await db.latestAccountHeaders.toArray();

// Get the single chain-progress row (primary key 1)
const current = await db.blockchainCheckpoint.get(1);

// Look up a header by its `id` index (header PK is `id`)
const record = await db.latestAccountHeaders
  .where("id")
  .equals(accountId)
  .first();

// Filter a single-field index, optionally narrowing with `.and(...)`
const slots = await db.latestAccountStorages
  .where("accountId")
  .equals(accountId)
  .and((record) => nameSet.has(record.slotName))
  .toArray();

// Match multiple keys against one index
const codes = await db.accountCodes.where("root").anyOf(codeRoots).toArray();

// InputNotes carries a `scriptRoot` index, backing getInputNotesFromScriptRoots
const notes = await db.inputNotes
  .where("scriptRoot")
  .anyOf(scriptRoots)
  .toArray();
```

The current `InputNotes` index string is
`"detailsCommitment,noteId,nullifier,scriptRoot,stateDiscriminant,[consumedBlockHeight+consumedTxOrder+detailsCommitment]"`.
The `noteId` form remains only in the intentionally frozen v1 baseline; Dexie v3 replaces it.

For compound indexes, use the **bracket-string** index name and pass the
key parts as an array to `.equals(...)` (from `applyAccountPatch` in
`accounts.ts`):

```typescript
const oldSlot = await db.latestAccountStorages
  .where("[accountId+slotName]")
  .equals([accountId, slot.slotName])
  .first();
```

### Latest vs Historical

For account state, the `latest…` tables hold the current row (keyed by
`accountId`, or the compound `[accountId+slotName]` / `[accountId+vaultKey]`
/ `[accountId+slotName+key]`); the matching `historical…` tables hold the
value that was replaced, with the prior value in `oldSlotValue` /
`oldAsset` / `oldValue` (`null` when no previous value existed). Their
primary keys are the fuller compounds
`[accountId+replacedAtNonce+slotName]`,
`[accountId+replacedAtNonce+slotName+key]` and
`[accountId+replacedAtNonce+vaultKey]`, with `[accountId+replacedAtNonce]`
as a secondary index.

The write path is **archive-then-replace-or-delete**: read the current
latest row, `put` it into historical under the new nonce, then either `put`
the new value into latest or delete the latest row. See `applyAccountPatch`
(incremental, driven by a patch) and `applyFullAccountState` (wholesale
replacement) in `accounts.ts`. The delete branches:

- A `JsStorageSlot` carries an optional `patchOperation?: number`, produced
  Rust-side from `patch_op().as_u8()`
  (`crates/idxdb-store/src/account/utils.rs`). Do not assume a full
  numeric mapping; only two branches are implemented.
- For a **map** slot (`slotType === STORAGE_SLOT_TYPE_MAP`, the exported
  constant `1`) with `patchOperation === 0 || patchOperation === 2`, every
  persisted map entry for that slot is archived and the whole latest map
  slot is deleted.
- `patchOperation === 2` additionally **deletes** the latest storage-slot
  row rather than `put`-ing it.
- For map entries and vault assets, an empty-string value (`""`) means
  removal: archive the old value, then delete the latest row.

`applyAccountPatch` full signature (bound Rust-side as
`#[wasm_bindgen(js_name = applyAccountPatch)]` in
`crates/idxdb-store/src/account/js_bindings.rs`):

```typescript
applyAccountPatch(
  dbId, accountId, nonce,
  updatedSlots: JsStorageSlot[],
  changedMapEntries: JsStorageMapEntry[],
  changedAssets: JsVaultAsset[],
  codeRoot, storageRoot, vaultRoot, committed, commitment
)
```

Undo restores from history back to latest, keyed by the compound nonce
index; a non-null old value overwrites latest, a `null` old value deletes
the latest row (from the module-private `restoreSlotsFromHistorical(db,
accountId, nonce)` in `accounts.ts`):

```typescript
const oldSlots = await db.historicalAccountStorages
  .where("[accountId+replacedAtNonce]")
  .equals([accountId, nonce])
  .toArray();

for (const slot of oldSlots) {
  if (slot.oldSlotValue !== null) {
    await db.latestAccountStorages.put({ /* ...restore old value... */ });
  } else {
    await db.latestAccountStorages
      .where("[accountId+slotName]")
      .equals([accountId, slot.slotName])
      .delete();
  }
}
```

`pruneAccountHistory` (the JS function in `accounts.ts`, reached from the
low-level WASM `WebClient.pruneAccountHistory` — it is **not** a method on
the high-level `MidenClient`) drops `historical…` rows whose
`replacedAtNonce <= upToNonce` and any orphaned account code. Write
functions must keep the latest row authoritative regardless of how much
history has been pruned.

### The account forest is not in Dexie

`crates/idxdb-store/src/forest.rs` holds an in-memory `AccountSmtForest`
over a `ForestInMemoryBackend`, with a monotonic `VersionId`. The forest
backend is synchronous while IndexedDB is async, so the forest is rebuilt
from the account tables on store open, is forward-only, and is recovered
via `IdxdbStore::rebuild_account_forest`. Asset and storage-map
**witnesses** are served from the forest, not from a Dexie query — do not
add a table to try to persist them.

### Serialization Conventions

- Hex strings for cryptographic values (hashes, IDs, commitments, vault keys)
- `uint8ArrayToBase64()` (from `./utils.js`) when a `Uint8Array` must be
  returned to Rust as a base64 string (e.g. serialized account code, seeds)
- `Uint8Array` for direct binary storage in a table column
- Default empty strings for optional string fields when reading out:
  `record.storageRoot || ""`
- `BigInt()` for nonce comparisons and sorting (nonces are stored as
  strings, so lexicographic / index-range ordering would be wrong)

## Upsert Pattern

Dexie `Table.put()` is itself an upsert: it inserts or replaces by primary
key. The store builds a plain data object and calls `.put()` — it does not
read-then-branch. Convert `null` to `undefined` so Dexie omits the field
from indexes (a `null` in a compound index is a real value; an absent
field is skipped). From `upsertInputNote` in
`crates/idxdb-store/src/ts/notes.ts`:

```typescript
export async function upsertInputNote(
  dbId: string,
  detailsCommitment: string,
  noteId: string | undefined,
  // ... more params
  consumedBlockHeight?: number | null,
  consumedTxOrder?: number | null,
  consumerAccountId?: string | null,
  tx?: Transaction
) {
  const db = getDatabase(dbId);
  const doWork = async (t: Transaction) => {
    try {
      const data = {
        detailsCommitment,
        noteId: noteId ?? undefined,
        scriptRoot,
        // null -> undefined so Dexie omits these from compound indexes
        consumedBlockHeight: consumedBlockHeight ?? undefined,
        consumedTxOrder: consumedTxOrder ?? undefined,
        consumerAccountId: consumerAccountId ?? undefined,
        // ... remaining fields
      };
      await t.inputNotes.put(data);
      await t.notesScripts.put({ scriptRoot, serializedNoteScript });
    } catch (error) {
      logWebStoreError(error, `Error inserting note: ${detailsCommitment}`);
      throw error;
    }
  };
  // Run inside the caller's tx if provided, else open one.
  if (tx) return doWork(tx);
  return db.dexie.transaction("rw", db.inputNotes, db.notesScripts, doWork);
}
```
