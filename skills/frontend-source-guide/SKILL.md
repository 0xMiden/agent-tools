---
name: frontend-source-guide
description: Guide for advanced Miden frontend development using source repo exploration. Covers AI development practices (Plan Mode, verification-driven development, context engineering, sub-agents) and maps the Miden web-sdk source repository for discovering advanced patterns. Use when building complex applications beyond basic hook usage, implementing custom signers, working with WasmWebClient directly, or troubleshooting SDK internals.
---

# Advanced Miden Frontend Development: Source-Guided Context Engineering

Every path and symbol below is verified against `web-sdk` at tag `v0.16.0-rc.7`.

## Development Approach

### 1. Plan Mode First

For any non-trivial frontend application, start in Plan Mode before writing code.

- Explore React SDK source and the example wallet to understand available patterns
- Design the component hierarchy, data flow, and which hooks to use
- Identify which built-in hooks cover your needs vs what requires direct `WasmWebClient` access
- Map out the user flow: account creation, token operations, note handling

Rule of thumb: if the task involves custom transactions, external signers, or patterns not covered by the basic skills, plan first.

### 2. Verification-Driven Development

This is the single highest-leverage practice for AI-assisted frontend development.

**Type check loop**: After every file edit, run `npx tsc --noEmit` (this is the shape of the SDK's own `typecheck` script in `packages/react-sdk/package.json`). If types fail:

1. Read the error message
2. Search the React SDK source for the correct type signature or hook usage — `packages/react-sdk/src/types/index.ts` is the single source of truth for option and result types
3. Adapt the working pattern to your use case
4. Recheck

**Dev server loop**: Run the app and check the browser. When something fails:

1. Check the browser console for WASM errors, network errors, or React errors
2. Branch on `error.code`, not message text — see `frontend-pitfalls` FP11 for the code sets
3. For WASM load errors: check Vite config and (only if you opted into the `/mt` build) COOP/COEP headers — see `vite-wasm-setup` and `frontend-pitfalls` FP3/FP8
4. For unexpected behavior: compare your code against the example wallet at `packages/react-sdk/examples/wallet/`

Never submit code that doesn't type-check. The verification loop is your quality guarantee.

### 3. Context Engineering with Source Repos

The basic skills (`react-sdk-patterns`, `frontend-pitfalls`, `vite-wasm-setup`, `wasm-bridge`) cover standard patterns. For anything beyond those, the web-sdk source repository is the knowledge base.

**How to use source repos effectively**:

- Don't load entire repos into context. Use sub-agents to explore — they search, read relevant files, and summarize findings without filling the main conversation context.
- Read source files only when you need a specific answer (progressive disclosure)
- Look for working examples first, then adapt. The example wallet app is the most reliable reference.
- When you find a useful pattern in source, extract just what you need — the exact hook call, the exact type, the exact provider setup.
- **Pin your reading to the version you are building against.** The SDK moves fast; a pattern read off the default branch may not exist in your installed version.

**Using sub-agents for exploration**:

- Launch an explore sub-agent with a specific question: "Find how `useSwap` handles the payback note type in the React SDK"
- The sub-agent searches, reads the relevant files, and returns a focused summary
- Your main context stays clean for implementation

### 4. Iterative Frontend Development

Break complex applications into stages. Complete each before starting the next:

1. **Design** (Plan Mode) — Component hierarchy, data flow, hook selection
2. **Provider setup** — `MidenProvider` config, signer integration if needed
3. **Query components** — Account display, balance rendering, note lists
4. **Mutation components** — Send forms, mint buttons, consume flows
5. **Transaction UX** — Stage progress (`TransactionStage`), error handling, loading states
6. **Polish** — Auto-sync tuning, memoization, edge cases

When stuck at any stage: search the React SDK source for a similar working pattern. Adapt it, don't guess.

---

## Miden Source Repository Map

Clone the repo at the tag you build against, alongside your project:

```bash
# Contains the React SDK source (@miden-sdk/react), the WASM client bindings
# (@miden-sdk/miden-sdk), the Vite plugin, and a working example wallet.
git clone --depth 1 --branch v0.16.0-rc.7 https://github.com/0xMiden/web-sdk.git ../web-sdk
```

Workspace layout at the tag: `crates/` holds `web-client`, `idxdb-store`, `js-export-macro`, `mobile-prover`; `packages/` holds `react-sdk`, `vite-plugin`, and the prebuilt `node-sdk-*` binaries.

### `packages/react-sdk/` — React SDK Source (`@miden-sdk/react`)

The primary reference for all frontend development.

- **`packages/react-sdk/src/index.ts`** — The public surface. Read this first: it is the authoritative list of what the package exports, and it groups the hooks for you.
- **`packages/react-sdk/src/hooks/`** — **37 hook implementations**, one file each, all re-exported from `index.ts` (10 query hooks + 27 mutation hooks). Each file is self-contained; read it for exact parameters, error handling, and stage progression.
  - *Query*: `useAccounts`, `useAccount`, `useNotes`, `useNoteStream`, `useTransactionHistory`, `useSyncState`, `useAssetMetadata`, `usePswapLineages`, `usePswapLineagesFor`, `usePswapLineage`
  - *Mutation*: `useCreateWallet`, `useCreateFaucet`, `useImportAccount`, `useSend`, `useMultiSend`, `useWaitForCommit`, `useWaitForNotes`, `useMint`, `useBridge`, `useConsume`, `useSwap`, `usePswapCreate`, `usePswapConsume`, `usePswapCancel`, `usePswapCancelByOrder`, `useCreateNetworkNote`, `useTransaction`, `useChainAnchor`, `usePreview`, `useExecuteProgram`, `useCompile`, `useSessionAccount`, `useExportStore`, `useImportStore`, `useImportNote`, `useExportNote`, `useSyncControl`
- **`packages/react-sdk/src/context/MidenProvider.tsx`** — Client initialization, sync loop, signer detection, the `runExclusive` `AsyncLock`. Read this to understand initialization order. It defines **two** of the four context hooks that live outside `src/hooks/`: `useMiden()` and `useMidenClient()` (the latter returns the low-level `WasmWebClient`, imported here under the local alias `WebClient`). The other two are `useSigner` in `context/SignerContext.ts` and `useMultiSigner` in `context/MultiSignerProvider.tsx`.
- **`packages/react-sdk/src/context/SignerContext.ts`** — External signer interface (`SignerContextValue`, `SignCallback`) and `useSigner()`. Read this when implementing custom signers.
- **`packages/react-sdk/src/context/MultiSignerProvider.tsx`** — `MultiSignerProvider`, `SignerSlot`, `useMultiSigner()`. Read this when an app must offer several signer providers side by side, as the example wallet does.
- **`packages/react-sdk/src/store/MidenStore.ts`** — Zustand store (`useMidenStore`) plus narrow selector hooks. Read this to understand cached state and what triggers re-renders.
- **`packages/react-sdk/src/types/index.ts`** — All option, result, and configuration interfaces, plus the `DEFAULTS` constant. The single source of truth.
- **`packages/react-sdk/src/utils/`** — 17 utility modules: `accountBech32`, `accountId`, `accountParsing`, `amounts`, `asyncLock`, `bytes`, `errors`, `network`, `noteAttachment`, `noteFilters`, `notes`, `prover`, `runExclusive`, `signerAccount`, `storage`, `transactions`, `walletDetection`.
- **`packages/react-sdk/examples/wallet/`** — Complete working wallet app (`src/main.tsx`, `src/App.tsx`, `src/SignerSelector.tsx`, `vite.config.ts`). The most reliable reference for provider setup, account creation, balances, claiming notes, and sending tokens.
- **`packages/react-sdk/README.md`**, **`packages/react-sdk/CLAUDE.md`** — Package-level prose docs.

**Explore when**: Writing any new component, understanding exact hook behavior, finding how a specific feature works, debugging unexpected behavior.

### `crates/web-client/` — WASM Client Bindings (`@miden-sdk/miden-sdk`)

The Rust-to-WASM bridge that the React SDK wraps. See the `wasm-bridge` skill for how the JS and Rust layers fit together.

- **`crates/web-client/js/index.js`** — The JS `WebClient` wrapper exported as `WasmWebClient`, its method-classification sets, the forwarding `Proxy`, and the WASM call-serialization chain.
- **`crates/web-client/js/client.js`** — The high-level `MidenClient` — the recommended entry point, which composes the resource APIs below.
- **`crates/web-client/js/resources/`** — 8 resource modules that make up the high-level API: `accounts.js`, `compiler.js`, `keystore.js`, `notes.js`, `pswap.js`, `settings.js`, `tags.js`, `transactions.js`.
- **`crates/web-client/js/types/api-types.d.ts`** — TypeScript surface for the high-level `MidenClient` and `ClientOptions`. **`crates/web-client/js/types/index.d.ts`** — the package entry types, including the `@internal` `WasmWebClient` declaration.
- **`crates/web-client/js/syncLock.js`** — `withSyncLock`, the Web Locks coalescing/serialization used by the sync entry points. `crates/web-client/js/webLock.js` (`withWriteLock`) and `crates/web-client/js/asyncLock.js` (`AsyncLock`) are neither published (absent from the package's `files` array) nor imported by any entry module, and their only in-tree callers are their own tests — read them for the pattern, but they are not on the hot path.
- **`crates/web-client/js/eager.js`** — Why the default entry uses top-level await and when to import `/lazy` instead.
- **`crates/web-client/src/models/`** — One Rust file per JS-visible model type (`account_id.rs`, `note.rs`, `transaction_request/`, `provers.rs`, …). This is where JS method names and argument types are actually declared, via `#[js_export(js_name = "...")]`.
- **`crates/web-client/src/rpc_client/`** — The standalone `RpcClient` (`getBlockHeaderByNumber`, `getNotesById`, `getAccountDetails`, `getAccountProof`, `syncNotes`, `getNetworkNoteStatus`, …). Exported separately from `@miden-sdk/miden-sdk`; **not** reachable through `useMidenClient()`.
- **`crates/web-client/README.md`** — Entry-point matrix (ST/MT × eager/lazy), cross-origin isolation guidance, `initThreadPool`.

**Explore when**: A hook doesn't exist for your operation, working out what methods the client actually exposes, debugging WASM-level errors.

### `crates/idxdb-store/` — IndexedDB Persistence

The browser storage layer for accounts, keys, notes, and transaction history.

- **`crates/idxdb-store/src/ts/schema.ts`** — Dexie schema, version blocks, and `ensureClientVersion` (the routine that deletes the database on a major/minor client-version bump — see `frontend-pitfalls` FP7).
- **`crates/idxdb-store/src/ts/`** — Per-table logic: `accounts.ts`, `auth.ts`, `chainData.ts`, `notes.ts`, `settings.ts`, `sync.ts`, `transactions.ts`, plus `export.ts` / `import.ts` for store dumps.

**Explore when**: Debugging data persistence issues, understanding what's stored in IndexedDB, investigating storage isolation for external signers. See also the `idxdb-patterns` skill.

---

## What to Explore for Each Pattern

Paths are relative to the repo root.

| Building This | Explore These Paths | What to Look For |
|---|---|---|
| Basic wallet UI | `packages/react-sdk/examples/wallet/` | `MidenProvider` setup, `useAccounts`, `useSend` |
| Custom transaction | `packages/react-sdk/src/hooks/useTransaction.ts` | Request-factory pattern, the execute → prove → submit → apply pipeline |
| External signer | `packages/react-sdk/src/context/SignerContext.ts` | `SignerContextValue` interface, `signCb`, `storeName` |
| Several signers in one app | `packages/react-sdk/src/context/MultiSignerProvider.tsx` | `SignerSlot`, `useMultiSigner` |
| Note consumption flow | `packages/react-sdk/src/hooks/useConsume.ts` | `NoteId` parsing, `NoteFilter` construction |
| Swap UI | `packages/react-sdk/src/hooks/useSwap.ts` | `SwapOptions`, separate `noteType` and `paybackNoteType` |
| Partial swap (PSWAP) UI | `packages/react-sdk/src/hooks/usePswapCreate.ts`, `usePswapConsume.ts`, `usePswapCancel.ts`, `usePswapCancelByOrder.ts` | Partial-fill swap flow: create, consume, cancel |
| PSWAP order tracking | `packages/react-sdk/src/hooks/usePswapLineage.ts`, `usePswapLineages.ts`, `usePswapLineagesFor.ts` | Lineage records for partially-filled orders |
| Token display | `packages/react-sdk/src/utils/amounts.ts` | `formatAssetAmount`, `parseAssetAmount` |
| Account ID formatting | `packages/react-sdk/src/utils/accountBech32.ts` | `toBech32AccountId`, `bech32id()` prototype install |
| Network / RPC resolution | `packages/react-sdk/src/utils/network.ts` | Which `rpcUrl` shorthands resolve, and which pass through |
| State management | `packages/react-sdk/src/store/MidenStore.ts` | Zustand selectors, cached state |
| Direct `WasmWebClient` usage | `packages/react-sdk/src/context/MidenProvider.tsx` | `useMidenClient()`, `runExclusive` |
| Multi-step workflow | `packages/react-sdk/src/hooks/useWaitForCommit.ts`, `useWaitForNotes.ts` | Polling loops, `timeoutMs` / `intervalMs` defaults |
| Prover selection & fallback | `packages/react-sdk/src/utils/prover.ts` | `resolveTransactionProver`, `proveWithFallback` |
| Structured error handling | `packages/react-sdk/src/utils/errors.ts` | `MidenError`, `MidenErrorCode`, `WasmErrorCode`, `CodedError` |
| Backup / restore | `packages/react-sdk/src/hooks/useExportStore.ts`, `useImportStore.ts` | `exportStore(storeName)`, `importStore(storeName, dump)` |
| Pausing background sync | `packages/react-sdk/src/hooks/useSyncControl.ts` | `pauseSync`, `resumeSync`, `isPaused` |
| Compiling MASM from the browser | `packages/react-sdk/src/hooks/useCompile.ts`, `crates/web-client/js/resources/compiler.js` | `CompilerResource`; `component()` / `txScript()` / `noteScript()` |

---

## Common Advanced Patterns

### Custom Hooks Wrapping `WasmWebClient`

For operations not covered by built-in hooks, write a custom hook over `useMidenClient()`. It returns the low-level `WasmWebClient`, so only call methods that exist on it — `crates/web-client/js/index.js` lists many of them in its `SYNC_METHODS` / `WRITE_METHODS` / `READ_METHODS` sets — but those sets are **not** exhaustive. `check-method-classification.js` also accepts a method defined as an explicit wrapper on the JS `WebClient` class, which is how `syncState`, `syncChain`, `syncNoteTransport`, `executeTransaction`, `proveTransaction`, `applyTransaction`, `newWallet`, `newFaucet`, `newAccount` and the `submitNewTransaction*` pair are reachable while appearing in none of the three sets. Check the class body too.

Wrap **multi-call sequences** in `runExclusive` so nothing interleaves between your calls (see `frontend-pitfalls` FP2); a lone call already serializes itself.

```tsx
function useSyncHeight() {
  const client = useMidenClient();
  const [height, setHeight] = useState<number | null>(null);
  useEffect(() => {
    // getSyncHeight is a READ_METHOD forwarded through the client proxy,
    // which serializes it — no runExclusive needed for a single call.
    client.getSyncHeight().then(setHeight);
  }, [client]);
  return height;
}
```

Some operations are **not** on the client returned by `useMidenClient()` — block headers, for instance. `getBlockHeaderByNumber` lives on the standalone `RpcClient`, which you construct directly with an `Endpoint`:

```tsx
import { RpcClient, Endpoint } from "@miden-sdk/miden-sdk";

// Endpoint: new Endpoint(url), or Endpoint.testnet() / Endpoint.devnet()
const rpc = new RpcClient(Endpoint.testnet());

// getBlockHeaderByNumber(blockNum?: number, includeMmrProof?: boolean)
const header = await rpc.getBlockHeaderByNumber(blockNumber, false);
```

### Multi-Step Workflows

Compose hooks for complex flows (mint → wait for commit → wait for notes → consume). `useMint` resolves to `TransactionResult { transactionId: string }`; `waitForConsumableNotes` resolves to `ConsumableNoteRecord[]`, and `ConsumeOptions.notes` accepts `InputNoteRecord` objects, so unwrap each record with `.inputNoteRecord()`:

```tsx
const { mint } = useMint();
const { waitForCommit } = useWaitForCommit();
const { waitForConsumableNotes } = useWaitForNotes();
const { consume } = useConsume();

const mintAndConsume = async () => {
  const { transactionId } = await mint({ targetAccountId, faucetId, amount: 1000n });
  await waitForCommit(transactionId);                      // default 10s timeout, 1s poll
  const records = await waitForConsumableNotes({ accountId: targetAccountId });
  await consume({
    accountId: targetAccountId,
    notes: records.map((r) => r.inputNoteRecord()),
  });
};
```

Both wait hooks default to `timeoutMs: 10000` and `intervalMs: 1000`; `waitForConsumableNotes` also takes `minCount` (default `1`). Raise the timeout for slow networks rather than looping the hook yourself.

### Custom Signer Implementation

Implement `SignerContextValue` and wrap `MidenProvider` in your provider. Read `packages/react-sdk/src/context/SignerContext.ts` for the exact contract: `signCb` is required; `getKeyCb` / `insertKeyCb` are optional; `accountConfig`, `storeName`, `name`, `isConnected`, `connect`, and `disconnect` complete the interface.

`storeName` must be unique per user — `MidenProvider` derives the IndexedDB database name from it (`MidenClientDB_<storeName>`), so a shared value would let two identities share one store.

To offer several signers in one app, use `MultiSignerProvider` + `SignerSlot`, as `packages/react-sdk/examples/wallet/src/main.tsx` does.
