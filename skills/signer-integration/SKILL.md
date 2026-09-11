---
name: signer-integration
description: Guide to integrating external signers (Para, Turnkey, MidenFi wallet adapter) and building custom signers for Miden React frontends. Covers provider setup and nesting, the MultiSignerProvider registry, the unified useSigner interface, custom SignerContext implementation, custom account components, wallet-extension detection, and network-account/network-note targeting. Use when adding wallet connection, authentication, or external key management to a Miden frontend.
---

# Miden Signer Integration

```json
{
  "@miden-sdk/react": "0.16.0-rc.7",
  "@miden-sdk/miden-sdk": "0.16.0-rc.7",
  "@miden-sdk/para-react": "0.16.0-rc.7",
  "@miden-sdk/turnkey-react": "0.16.0-rc.7",
  "@miden-sdk/miden-wallet-adapter-react": "0.16.0-rc.7",
  "@miden-sdk/miden-wallet-adapter-base": "0.16.0-rc.7"
}
```

## Overview

By default, `MidenProvider` uses a **local keystore** (keys in IndexedDB, no wallet connection needed). For production apps, mount a signer provider so `MidenProvider` builds its client with an external keystore instead.

`MidenProvider` reads the **nearest ancestor** `SignerContext`. So a single signer provider must wrap it (outer → inner):

```
<SignerProvider>      ← populates SignerContext: signCb + accountConfig + storeName
  <MidenProvider>     ← picks it up and calls WebClient.createClientWithExternalKeystore(...)
    <App />
  </MidenProvider>
</SignerProvider>
```

When a signer context is present, the IndexedDB name becomes `` `MidenClientDB_${signer.storeName}` `` and every write signs through `signer.signCb`. No per-hook wiring is needed — `useSend`, `useConsume` and the rest route through the same client.

**Init gate to be aware of:** while a signer ancestor exists but reports `isConnected === false`, `MidenProvider`'s init effect returns early and never creates a `WebClient`. On first mount that means `isReady` stays false and `useMidenClient()` throws, so even public reads cannot run until the user connects. If your app must render and read before connect, use the `MultiSignerProvider` arrangement below — it forwards `null` down to `MidenProvider` until a signer is actually selected, which puts the provider in local-keystore mode and lets it initialize immediately.

## Pre-Built Signer Providers

These packages are published from the web-sdk monorepo. Keep them on the same v0.16 release line as the React and web-client packages.

```tsx
import { ParaSignerProvider } from "@miden-sdk/para-react";
import { TurnkeySignerProvider } from "@miden-sdk/turnkey-react";
import { MidenFiSignerProvider } from "@miden-sdk/miden-wallet-adapter-react";
import { WalletAdapterNetwork } from "@miden-sdk/miden-wallet-adapter-base";
```

What the SDK's example app demonstrates:

```tsx
// Para (EVM wallets)
<ParaSignerProvider apiKey={import.meta.env.VITE_PARA_API_KEY} environment="BETA"> ... </ParaSignerProvider>

// Turnkey (passkey authentication)
<TurnkeySignerProvider config={{ defaultOrganizationId: organizationId }}> ... </TurnkeySignerProvider>

// MidenFi wallet (browser extension)
<MidenFiSignerProvider network={WalletAdapterNetwork.Testnet} autoConnect={false}> ... </MidenFiSignerProvider>
```

Notes on things agents commonly get wrong here:

- `MidenFiSignerProvider`'s `network` prop takes `WalletAdapterNetwork`; use `WalletAdapterNetwork.Testnet` for this guide's Testnet configuration.
- `useMidenFiWallet` is exported by `@miden-sdk/miden-wallet-adapter-react`, and `WalletReadyState` by the base package. The generic React SDK primitive `waitForWalletDetection` below remains useful for adapter-agnostic UI and tests.

## Wallet-extension detection

```tsx
import { waitForWalletDetection } from "@miden-sdk/react";
import type { WalletAdapterLike } from "@miden-sdk/react";

// WalletAdapterLike is a duck type with no dependency on any wallet-adapter package:
//   { readyState: string; on(e: "readyStateChange", cb): void; off(e: "readyStateChange", cb): void }

await waitForWalletDetection(adapter);         // default timeout: 5000 ms
await waitForWalletDetection(adapter, 10000);  // custom timeout
```

Resolves immediately when `adapter.readyState === "Installed"`; otherwise it listens for `readyStateChange` and rejects with `Wallet extension not detected within <n>ms. Is the browser extension installed and enabled?`. Use it to show an install prompt instead of blindly calling `connect()`.

## MultiSignerProvider — offering a choice of signer

Wrap everything in `MultiSignerProvider` and mount each signer provider — each containing a `<SignerSlot />` — as a **sibling** of `MidenProvider`:

```tsx
import { MidenProvider, MultiSignerProvider, SignerSlot, useMultiSigner } from "@miden-sdk/react";
import { WalletAdapterNetwork } from "@miden-sdk/miden-wallet-adapter-base";

<MultiSignerProvider>
  <ParaSignerProvider apiKey={apiKey} environment="BETA">
    <SignerSlot />
  </ParaSignerProvider>
  <TurnkeySignerProvider config={{ defaultOrganizationId: organizationId }}>
    <SignerSlot />
  </TurnkeySignerProvider>
  <MidenFiSignerProvider network={WalletAdapterNetwork.Testnet} autoConnect={false}>
    <SignerSlot />
  </MidenFiSignerProvider>
  <MidenProvider config={{ rpcUrl: "testnet", prover: "testnet" }}>
    <App />
  </MidenProvider>
</MultiSignerProvider>
```

`SignerSlot` renders nothing: it reads its nearest ancestor's `SignerContext` value and registers it into `MultiSignerProvider`'s registry. `MultiSignerProvider` then supplies `MidenProvider`'s `SignerContext` with only the **active** signer — or `null` when none is selected, which is what keeps the app in local-keystore mode (and therefore readable) before the user picks one.

```tsx
const multiSigner = useMultiSigner();          // null outside a MultiSignerProvider
const { signers, activeSigner, connectSigner, disconnectSigner } = multiSigner ?? {};

await connectSigner("Turnkey");   // sets active by `name`, then calls that signer's connect()
await disconnectSigner();         // clears the active signer → back to local keystore mode
```

`connectSigner(name)` throws `Signer "<name>" not found` for an unregistered name, disconnects the previous signer fire-and-forget, and reverts the active name to `null` if `connect()` rejects. Switching signers changes `storeName`, which makes `MidenProvider` drop its cached in-memory state and build a fresh client for the new identity; reconnecting the *same* identity hot-swaps `signCb` on the existing client instead.

A minimal selector:

```tsx
function SignerSelector({ onUseLocal }: { onUseLocal: () => void }) {
  const multiSigner = useMultiSigner();
  return (
    <>
      {multiSigner?.signers.map((s) => (
        <button key={s.name} onClick={() => multiSigner.connectSigner(s.name)}>{s.name}</button>
      ))}
      <button onClick={onUseLocal}>Use Local Keystore</button>
    </>
  );
}
```

## Unified Signer Interface

Works with any signer provider. `useSigner()` returns `SignerContextValue | null` — `null` in local-keystore mode (no signer provider mounted), so guard before destructuring:

```tsx
import { useSigner } from "@miden-sdk/react";

const signer = useSigner();
if (!signer) return null; // local keystore mode — no external signer

const { isConnected, connect, disconnect, name } = signer;

if (!isConnected) {
  return <button onClick={connect}>Connect {name}</button>;
}
```

## Building a Custom Signer

Implement `SignerContextValue` via `SignerContext.Provider`:

```tsx
import { SignerContext } from "@miden-sdk/react";
import { AccountStorageMode } from "@miden-sdk/miden-sdk";

<SignerContext.Provider value={{
  name: "MyWallet",
  storeName: `mywallet_${userAddress}`,  // unique per user for DB isolation
  isConnected: true,
  accountConfig: {
    publicKeyCommitment: userPublicKeyCommitment,  // Uint8Array
    storageMode: AccountStorageMode.private(),     // an AccountStorageMode instance, not a string
  },
  signCb: async (pubKey, signingInputs) => {
    // Route to your signing service. Both args are Uint8Array.
    return signature;  // Uint8Array
  },
  connect: async () => { /* trigger wallet connection */ },
  disconnect: async () => { /* clear session */ },
}}>
  <MidenProvider config={{ rpcUrl: "testnet" }}>
    <App />
  </MidenProvider>
</SignerContext.Provider>
```

**`SignerContextValue` fields:**

| Field | Required | Notes |
|---|---|---|
| `name` | yes | Display name; also the registry key used by `MultiSignerProvider` |
| `storeName` | yes | Unique per user — becomes the `MidenClientDB_<storeName>` IndexedDB name |
| `isConnected` | yes | `false` blocks client creation on first mount (see the init gate above) |
| `accountConfig` | yes | `SignerAccountConfig` (below); only meaningful when connected |
| `signCb` | yes | `(pubKey: Uint8Array, signingInputs: Uint8Array) => Promise<Uint8Array>` |
| `connect` / `disconnect` | yes | `() => Promise<void>` session lifecycle |
| `getKeyCb` | no | `(pubKey: Uint8Array) => Promise<Uint8Array>` — retrieve a secret key by commitment |
| `insertKeyCb` | no | `(pubKey: Uint8Array, secretKey: Uint8Array) => void` — persist a generated key pair |

**`SignerAccountConfig` fields:**

| Field | Required | Notes |
|---|---|---|
| `publicKeyCommitment` | yes | `Uint8Array`, deserialized to a `Word` for the auth component |
| `storageMode` | yes | an `AccountStorageMode` **instance** — `AccountStorageMode.private()` / `.public()` |
| `accountSeed` | no | `Uint8Array` for a deterministic account id; otherwise 32 random bytes |
| `customComponents` | no | `AccountComponent[]` appended after the basic wallet component |
| `importAccountId` | no | Skip the builder entirely and import this account id from chain |
| `accountType` | no | **`@deprecated` and ignored** — visibility comes solely from `storageMode`. Omit it. |

`signCb` is not called directly by `MidenProvider`; it is wrapped in a ref-reading callback so a reconnect of the same identity can hot-swap the callback without rebuilding the client. A wrapped call made after disconnect throws `Signer is disconnected. Cannot sign.`.

Two hooks additionally hard-block while a signer is mounted but disconnected — `useImportAccount` and `useMultiSend` call `assertSignerConnected()` and throw `Signer is disconnected. Reconnect your wallet to perform transactions.`

## How the account gets initialized

`MidenProvider` calls `initializeSignerAccount(client, accountConfig)` right after creating the external-keystore client. Two paths:

**Fast path — `importAccountId` is set.** The builder is skipped and `client.importAccountById(accountId)` runs. It tolerates exactly two error codes and rethrows everything else: `ACCOUNT_NOT_FOUND_ON_CHAIN` (a brand-new account not yet registered on-chain — the dApp still renders, but the account is *not* tracked locally, so `useAccount` returns `null` and no transaction can be built against it until a later import succeeds) and `ACCOUNT_ALREADY_TRACKED`. Use this path for wallets that mint accounts externally and hand over only an id.

**Slow path — build from the commitment.**

```ts
new AccountBuilder(seed)
  .withAuthComponent(
    AccountComponent.createAuthComponentFromCommitment(commitmentWord, AuthScheme.AuthEcdsaK256Keccak)
  )
  .storageMode(config.storageMode)
  .withBasicWalletComponent()
  // then .withComponent(c) for each entry in customComponents
  .build();
```

For a **public** storage mode it first tries `importAccountById` (the account may already exist on-chain). If that **succeeds**, it syncs and returns the account id immediately — `getAccount` and `newAccount` are never reached. Only when the import throws does it fall through to checking `client.getAccount(accountId)` for a local copy and finally creating the account with `client.newAccount(account, false)`.

Note the hard-coded `AuthScheme.AuthEcdsaK256Keccak` on the auth component: an external signer's commitment is registered as an ECDSA-K256/Keccak key, not Falcon.

> **Two different things are called `AuthScheme`, and the wrong one is the default import.** The numeric WASM enum (`AuthEcdsaK256Keccak = 1`, `AuthRpoFalcon512 = 2`) is the Rust model. But the `AuthScheme` that `@miden-sdk/miden-sdk` actually exports is a frozen *string* const — `{ Falcon: "falcon", ECDSA: "ecdsa" }` — declared in both the browser and Node entries, and it **shadows** the WASM binding. So `AuthScheme.AuthEcdsaK256Keccak` evaluates to `undefined` against the real package. On Node the WASM class is re-exported under the non-colliding alias `AuthSchemeNative`; the browser entry has no escape hatch, which is why the SDK's own browser test harness restores it by hand (`window.AuthScheme = wasm.AuthScheme`). Pass the numeric value directly, or use `AuthSchemeNative` on Node.

`withAuthComponent(component)` exists on the JS `AccountBuilder` and is the primary auth path — it forwards to `with_component` internally. Use it; do not look for a replacement. Sibling builder methods: `withComponent`, `withNoAuthComponent`, `withBasicWalletComponent`, `accountType`, `storageMode`, `build`, `buildWithoutSchemaCommitment`.

## Custom Account Components

Attach application-specific `AccountComponent` instances (e.g. DEX logic from a compiled `.masp` package) to the account the signer creates:

```tsx
import { type SignerAccountConfig } from "@miden-sdk/react";
import { AccountComponent, AccountStorageMode } from "@miden-sdk/miden-sdk";

const myDexComponent: AccountComponent = await loadCompiledComponent();

const accountConfig: SignerAccountConfig = {
  publicKeyCommitment: userPublicKeyCommitment,
  storageMode: AccountStorageMode.public(),
  customComponents: [myDexComponent],
};
```

Each entry must be a real `AccountComponent` — created via `AccountComponent.compile()`, `.fromPackage()` or `.fromLibrary()`. The initializer duck-checks for a `getProcedures` method and throws otherwise:

> Each entry in customComponents must be an AccountComponent instance created via AccountComponent.compile(), AccountComponent.fromPackage(), or AccountComponent.fromLibrary().

Components are appended to the `AccountBuilder` after the default basic wallet component. The field is optional — omitting it preserves default behavior. `SignerAccountConfig.accountType` is deprecated and ignored; omit it.

## Network accounts and network notes

There **is** a network-execution surface. A network note is a Public note carrying a `NetworkAccountTarget` attachment; once it lands on-chain the targeted network account auto-consumes it, with no manual `consume` on the recipient side.

### Targeting

```tsx
import { NetworkAccountTarget, NoteExecutionHint } from "@miden-sdk/miden-sdk";

const target = new NetworkAccountTarget(networkAccountId, NoteExecutionHint.always());
// executionHint is optional and defaults to `always`.
// The constructor errors if `accountId` is not a public account.

target.targetId();        // AccountId
target.executionHint();   // NoteExecutionHint
const attachment = target.toAttachment();                  // NoteAttachment
NetworkAccountTarget.fromAttachment(attachment);           // decode back; errors if not a target attachment
```

### Building the note

```tsx
// Note.withAttachments(noteAssets, noteMetadata, noteRecipient, attachments)
// Uses the metadata's sender / note type / tag; attachments on the metadata itself are ignored.
const note = Note.withAttachments(noteAssets, metadata, recipient, [target.toAttachment(), extra]);
note.attachments();     // NoteAttachment[]
note.isNetworkNote();   // true — Public + a valid NetworkAccountTarget attachment
```

From React:

```tsx
import { useCreateNetworkNote } from "@miden-sdk/react";

const { createNetworkNote, result, isLoading, stage, error, reset } = useCreateNetworkNote();
const { txId, note } = await createNetworkNote({
  accountId: senderId,       // AccountRef — creates, funds and submits the note
  target: networkAccountId,  // AccountRef
  script: myNoteScript,      // NoteScript — OR `recipient`, exactly one of the two
  executionHint,             // optional; defaults to `always`
  inputs: [1n, 2n],          // optional note storage / inputs (used with `script`)
  assetId, amount,           // optional single asset to lock into the note
  attachment: [1n, 2n, 3n],  // optional extra payload appended after the NetworkAccountTarget
});
```

Passing both `recipient` and `script`, or neither, throws. From the raw client the equivalent is `client.transactions.createNetworkNote(options)`, which resolves to `{ txId, note, result }`; There is also a `buildNetworkNote(opts)` that builds the same note without submitting — but at this pin it is **not importable** from `@miden-sdk/miden-sdk`: it exists in `js/standalone.js` and is declared in `api-types.d.ts`, yet neither package entry re-exports it (they re-export only `createP2IDNote`, `createP2IDENote` and `buildSwapTag`). Treat the type declaration as aspirational until an entry exports it.

### Creating the network account

A network account is a **public** account carrying the network-account auth component, whose note-script allowlist is what the node's network-transaction builder inspects:

```tsx
import { AccountBuilder, AccountComponent, AccountStorageMode, NoteScriptFee } from "@miden-sdk/miden-sdk";

// Returns AccountComponent[] — the auth component plus the components backing
// its fee policy. Install ALL of them.
const components = AccountComponent.createNetworkAuthComponents(
  [new NoteScriptFee(myNoteScript.root(), 0n)],  // NoteScriptFee[] — must be non-empty
  feeFaucetId,                                    // AccountId — fees are denominated in this faucet's asset
  allowedTxScriptRoots                            // optional Word[] from TransactionScript.root()
);

const builder = new AccountBuilder(seed)
  .storageMode(AccountStorageMode.public())
  .withComponent(myComponent);
for (const component of components) builder.withComponent(component);
const { account } = builder.build();
```

Rules that bite:

- The allowlist must be **non-empty** — `createNetworkAuthComponents([], ...)` throws, since such an account could never consume a note.
- Every allowlisted script is priced by construction. A fee of `0n` is valid; a script root the account does not price at all aborts fee estimation rather than being treated as free.
- Reuse the *same* compiled note script for the account allowlist and for the note, so the roots match. Targeting a plain wallet instead of a network account fails with `account procedure … is not in the account procedure index map`.
- The canonical expiration transaction script is always allowlisted (the node attaches it to every network transaction). Any other transaction script is forbidden unless its root is passed in the optional third argument — and only allowlist a root whose effect is safe for *every* possible input, since a root pins code but not the submitter-controlled arguments.
- Detect one with `account.isNetworkAccount()`; read the allowed roots with `account.networkNoteAllowlist()` (`Word[]`, or `undefined` for a non-network account).

### Ordinary attachments

Attachments are not network-specific. `NoteAttachment.fromWord(scheme, word)` / `fromWords(scheme, words)` build one, `.toWords()` reads it back, and `.attachmentScheme()` / `.numWords()` inspect it. The React SDK adds `createNoteAttachment(...)` / `readNoteAttachment(...)` helpers. The JS `NoteMetadata` constructor is attachment-less — `new NoteMetadata(sender, noteType, tag)` — so attach at the note level via `Note.withAttachments(...)`; there is no `metadata.withAttachment()` / `metadata.attachment()` / `metadata.withTag()`.

## Which Signer to Choose

| Signer | Auth Method | Keys Stored | Best For |
|--------|-------------|-------------|----------|
| Local keystore (default) | None | Browser IndexedDB | Development, demos |
| Para | EVM wallet | Para servers | Apps with existing EVM users |
| Turnkey | Passkey (biometric) | Turnkey servers | Consumer apps, no seed phrases |
| MidenFi Wallet | Browser extension | Extension | Power users with MidenFi wallet |
| Custom | Your choice | Your infrastructure | Enterprise, custom auth flows |

**Key trade-off**: Local keystore requires no setup but keys are lost if the user clears browser data. External signers persist keys elsewhere but add a dependency — and gate client initialization on connect unless you use `MultiSignerProvider`.
