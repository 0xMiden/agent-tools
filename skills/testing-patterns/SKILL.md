---
name: testing-patterns
description: Testing conventions for Miden frontend code — mocking @miden-sdk/react, the real hook return shapes to assert against, transaction-stage simulation, and the @miden-sdk/react mock shapes. Use when writing, running, or debugging tests for Miden React components.
---

# Miden Frontend Testing Patterns

The reference implementation for everything below is the Web SDK's **own** test suite, which ships
in the repository and can be read directly:

- `packages/react-sdk/src/__tests__/setup.ts` — the global `vi.mock("@miden-sdk/miden-sdk", …)`
- `packages/react-sdk/src/__tests__/mocks/miden-sdk.ts` — mock factories (`createMockWebClient`,
  `createMockAccountHeader`, `createMockAccountId`, …)
- `packages/react-sdk/src/__tests__/mocks/miden-sdk-entry.ts`
- `packages/react-sdk/src/__tests__/mocks/signer-context.ts`
- `packages/react-sdk/src/__tests__/hooks/` — one test file per hook
- `packages/react-sdk/src/__tests__/context/` — provider tests

Copy their shapes rather than inventing your own; they are kept in step with the hooks.

## Test Stack

The SDK itself runs **Vitest** with `@testing-library/react` and **jsdom**, configured in
`packages/react-sdk/vitest.config.ts`. The react-sdk package's own scripts are
`test` (`vitest run`), `test:coverage` (`vitest run --coverage`) and `typecheck` (`tsc --noEmit`).

## Mocking the SDK

Components that import from `@miden-sdk/react` need the SDK mocked, because the real package
initializes WASM. **Mock the hooks your component actually calls**, at the package boundary:

```tsx
import { render, screen } from "@testing-library/react";
import { useAccounts, useSend } from "@miden-sdk/react";
import { WalletView } from "../WalletView";

vi.mock("@miden-sdk/react", () => ({
  useAccounts: vi.fn(),
  useSend: vi.fn(),
}));

beforeEach(() => {
  vi.mocked(useAccounts).mockReturnValue({
    accounts: [], wallets: [], faucets: [],
    isLoading: false, error: null, refetch: vi.fn(),
  });
  vi.mocked(useSend).mockReturnValue({
    send: vi.fn(), result: null, isLoading: false,
    stage: "idle", error: null, reset: vi.fn(),
  });
});

it("shows the empty state", () => {
  render(<WalletView />);
  expect(screen.getByText(/no accounts/i)).toBeInTheDocument();
});
```

Override per test with `vi.mocked(useAccounts).mockReturnValue(...)`.

**Do not try to control a real hook by mocking `useMiden`.** Replacing only the public `useMiden`
export while leaving the real `useAccounts` in place does nothing: `useAccounts` imports `useMiden`
from its own internal module (`../context/MidenProvider`), not from the package entry point, so the
real provider hook still runs — and with no provider mounted it throws. Mock the hook you are
testing against, not its dependency.

**If you want the real hook logic**, render inside a real `MidenProvider` and mock the WASM boundary
instead, which is the level the SDK's own `setup.ts` mocks:

```tsx
vi.mock("@miden-sdk/miden-sdk", () => ({ /* ...mock client & model classes... */ }));
```

> **The SDK's own suite is not a consumer-copyable template.** It mocks *internal relative paths*
> (`vi.mock("../../context/MidenProvider", …)`) and resets `useMidenStore` in `beforeEach`. Neither
> is available to package consumers: `useMidenStore` is not a public export, and the package
> declares only the `.`, `./lazy`, `./mt`, `./mt/lazy` and `./package.json` subpaths — there is no
> way to reach internal modules from outside. Read that suite for mock *shapes*; use the boundary-level patterns
> above for your own app.

Reset mocks between tests with `vi.clearAllMocks()` in `beforeEach`. (The SDK's own suite also
resets its Zustand store with `useMidenStore.getState().reset()` — that is an internal module and is
not reachable from a consumer app, so if you mock at the hook boundary there is no shared store to
reset anyway.)

## Hook return shapes to assert against

These are the contract; getting them wrong is the most common source of tests that pass against a
mock and fail against the real SDK.

**Query hooks.** `useAccounts()` returns
`{ accounts, wallets, faucets, isLoading, error, refetch }`. Note two things about the real hook:
`wallets` is just `accounts` and `faucets` is always `[]` — both are deprecated, because an account
id does not distinguish a faucet from a wallet, so faucet-ness must be detected per-account from its
components. `error` is hardcoded `null`.

Query hooks are also **self-healing**: their effects are keyed on `isReady`, so a hook rendered
before the client is ready returns empty and then refetches itself once readiness flips. A test that
asserts "empty forever" is asserting something the hook does not do.

**Mutation hooks.** `useSend()` returns `{ send, result, isLoading, stage, error, reset }`. Its
result type is `SendResult { txId: string; note: Note | null }` — distinct from the
`TransactionResult { transactionId: string }` that `useMint` / `useConsume` / `useSwap` /
`useMultiSend` / `useTransaction` return. Mixing these two up is the single most common fixture bug.

`TransactionStage` is `"idle" | "executing" | "proving" | "submitting" | "complete"`.

```tsx
// mid-flight
vi.mocked(useSend).mockReturnValue({
  send: vi.fn(), result: null, isLoading: true,
  stage: "proving", error: null, reset: vi.fn(),
});

// completed — useSend returns SendResult { txId, note }
vi.mocked(useSend).mockReturnValue({
  send: vi.fn(), result: { txId: "0xabc123", note: null },
  isLoading: false, stage: "complete", error: null, reset: vi.fn(),
});

// other mutation hooks return TransactionResult { transactionId }
vi.mocked(useMint).mockReturnValue({
  mint: vi.fn(), result: { transactionId: "0xdef456" },
  isLoading: false, stage: "complete", error: null, reset: vi.fn(),
});
```

**Provider state.** `useMiden()` exposes `client`, `isReady`, `isInitializing`, `error`, `sync`,
`runExclusive`, `prover`, `signerAccountId`, and `signerConnected` (`boolean | null`, where `null`
means no signer provider is mounted).

**Sync state.** `useSyncState()` returns
`{ syncHeight: number; isSyncing: boolean; lastSyncTime: number | null; error: Error | null; sync: () => Promise<void> }` — `UseSyncStateResult` extends `SyncState` with `sync`, so a fixture built from the four state fields alone will make a component that calls `sync()` throw.

## Amounts are `bigint`

`AssetBalance.amount`, `NoteAsset.amount` and `useAccount().getBalance()` are all `bigint` on the TS
side. Option bags are more forgiving — `SendOptions.amount` is `bigint | number` and optional,
`MintOptions.amount` and `CreateFaucetOptions.maxSupply` are `bigint | number`.

Do not "fix" JS fixtures to the Rust client's `AssetAmount` type; that is a Rust-side concept and
does not cross the WASM boundary.

## Mock shapes that need checking

These shapes type-check against a loosely-typed fixture and then lie at runtime. Check each one against the current API:

- **`debugMode` does not exist.** `MidenConfig` is
  `{ rpcUrl?, noteTransportUrl?, autoSyncInterval?, seed?, prover?, proverUrls?, proverTimeoutMs?, useWorker? }`.
  Drop any `debugMode` field and any trailing `debugMode` argument to `createClient*`.
- **Transaction results expose `accountPatch()`, not `accountDelta()`**, and there is no
  `AccountStorageDelta`. The mirror image still holds: `TransactionSummary.accountDelta()` is
  unchanged and still returns a relative delta — do not "fix" that one for consistency.
- **`TransactionSummary` carries `userParams()` rather than a single `salt()`**, and the value is
  seven field elements. The whole summary preimage is six words: four leading commitments, then
  `expiration_delta` plus seven user params, 24 elements in total. A fixture mocking a four-word
  summary is wrong.

Pin `@miden-sdk/miden-sdk` and `@miden-sdk/react` to the **same exact** version — they link against
a shared WASM ABI, and a plain `"0.16"` or `^0.16.0` does not resolve a pre-release:

```json
{ "@miden-sdk/miden-sdk": "0.16.0-rc.7", "@miden-sdk/react": "0.16.0-rc.7" }
```

Hooks worth mocking that are easy to forget: `useBridge`, `useChainAnchor`, `useCompile`,
`useCreateNetworkNote`, `useExecuteProgram`, `useExportNote`, `useExportStore`, `useImportAccount`,
`useImportNote`, `useImportStore`, `useNoteStream`, `usePreview`, `usePswapCancel`,
`usePswapCancelByOrder`, `usePswapConsume`, `usePswapCreate`, `usePswapLineage` /
`usePswapLineages` / `usePswapLineagesFor`, `useSessionAccount`, `useSigner`, `useSyncControl`,
`useTransactionHistory`, `useWaitForCommit`, `useWaitForNotes`.

## Wallet connection state in tests

The only wallet surface that can be grounded against the SDK is what `@miden-sdk/react` itself
exports, so mock that and nothing else:

- **`useSigner()`** returns `SignerContextValue | null`. Its required members are `signCb`,
  `accountConfig`, `storeName`, `name`, `isConnected`, `connect` and `disconnect` (plus optional
  `getKeyCb` / `insertKeyCb`) — a fixture built from only the connection fields will not type-check.
- **`useMiden()`** exposes `signerAccountId` and `signerConnected`.
- **`waitForWalletDetection(adapter, timeoutMs = 5000)`** is the SDK's adapter-agnostic detection
  primitive. It takes a duck-typed `WalletAdapterLike { readyState: string; on/off("readyStateChange") }`,
  resolves once `readyState === "Installed"`, and rejects on timeout. Both it and the
  `WalletAdapterLike` type are exported from `@miden-sdk/react`, so a fake adapter object is enough
  to drive install-pending / installed states:

```tsx
const adapter: WalletAdapterLike = {
  readyState: "NotDetected",
  on: vi.fn(),
  off: vi.fn(),
};
```

Write wallet-connect UI against `useSigner()` and this duck type rather than against a specific
adapter package, and the tests stay valid whichever adapter ships.

> **Not covered here:** the concrete signer packages (`@miden-sdk/use-miden-para-react`,
> `@miden-sdk/miden-turnkey-react`, `@miden-sdk/miden-wallet-adapter-react`) live in repositories
> outside the Web SDK, so their props, exported hooks and versions cannot be established from it and
> this skill prescribes nothing about them. The SDK's own example composes signers as siblings under
> `MultiSignerProvider` with a `SignerSlot` each, and passes `MidenFiSignerProvider` a plain string
> (`network="testnet"`), not an enum member.

## Minimum coverage per component

1. **Success state** — renders correctly with data
2. **Loading state** — shows a loading indicator (`isLoading` / `isInitializing`)
3. **Error state** — shows the error and a recovery action
4. **User interactions** — buttons and forms call the right handler

## Common Mistakes

- **Not mocking the SDK.** Components importing `@miden-sdk/react` fail without a `vi.mock`, because
  the real provider initializes WASM before rendering children.
- **Confusing `SendResult` with `TransactionResult`.** `useSend` gives `{ txId, note }`; the others
  give `{ transactionId }`.
- **Asserting a permanently-empty query hook.** Query hooks refetch when `isReady` flips.
- **Carrying `debugMode` or `accountDelta()` forward** into fixtures.
- **Leaving mock state between tests.** Call `vi.clearAllMocks()` in `beforeEach`.
- **Mocking `useMiden` and expecting a real hook to notice.** `useAccounts` and friends import
  `useMiden` from an internal module, not from the package entry — mock the hook under test itself.
