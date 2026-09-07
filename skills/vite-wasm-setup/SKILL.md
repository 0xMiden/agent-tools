---
name: vite-wasm-setup
description: Guide to configuring Vite for Miden WASM applications. Covers the midenVitePlugin() setup and its four options, single- vs multi-threaded WASM entry points, COOP/COEP headers, production deployment headers, the Web Worker shim, TypeScript compatibility, and troubleshooting common Vite + WASM issues. Use when setting up a new Miden frontend, debugging build or runtime errors related to WASM or Vite configuration, or deploying to production.
---

# Vite + WASM Configuration for Miden

Everything below is current for `@miden-sdk/*` `0.16.0-rc.7` (web-sdk repo).

## Required `vite.config.ts`

```typescript
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { midenVitePlugin } from "@miden-sdk/vite-plugin";

export default defineConfig({
  plugins: [react(), midenVitePlugin()],
});
```

`midenVitePlugin` is exported both as a named export and as the default export,
and the plugin declares `enforce: "pre"` so it runs ahead of other plugins'
`config` hooks. It works with no options for the common case — the default
`@miden-sdk/miden-sdk` / `@miden-sdk/react` imports ship **single-threaded (ST)**
WASM that loads in any browser context, so the default client runs with no
cross-origin isolation. The in-repo example app
(`packages/react-sdk/examples/wallet/vite.config.ts`) is the source-of-truth
reference; it calls `midenVitePlugin()` bare alongside the Para plugin:

```typescript
plugins: [react(), midenVitePlugin(), paraVitePlugin()],
```

## Plugin Options

`MidenVitePluginOptions` has **four** options. All are optional; these are the
real defaults taken from the destructuring in `packages/vite-plugin/src/index.ts`:

| Option | Type | Default | Purpose |
|---|---|---|---|
| `wasmPackages` | `string[]` | `["@miden-sdk/miden-sdk"]` | Packages to alias, dedupe, and exclude from pre-bundling |
| `crossOriginIsolation` | `boolean` | `false` | Emit COOP/COEP headers on the dev + preview servers |
| `rpcProxyTarget` | `string \| false` | `"https://rpc.testnet.miden.io"` | gRPC-web dev proxy target; `false` disables the proxy |
| `rpcProxyPath` | `string` | `"/rpc.Api"` | Path prefix the dev proxy matches on |

```typescript
midenVitePlugin({
  wasmPackages: ["@miden-sdk/miden-sdk"],
  crossOriginIsolation: false,
  rpcProxyTarget: "https://rpc.testnet.miden.io",
  rpcProxyPath: "/rpc.Api",
});
```

> **Do not trust `packages/vite-plugin/README.md` for the
> `crossOriginIsolation` default.** At `0.16.0-rc.7` that README still shows
> `crossOriginIsolation: true, // default` and a `**Default:** \`true\`` bullet,
> while the executable source destructures `crossOriginIsolation = false` and a
> unit test asserts the plugin "does not set COOP/COEP headers by default"
> (`packages/vite-plugin/src/__tests__/config.test.ts`). The source wins.

Don't reach for `crossOriginIsolation: true` unless you have actually opted into
the multi-threaded build.

## Multi-Threaded (MT) WASM — Opt-In, Two Requirements

Pass `crossOriginIsolation: true` **only** if you import the multi-threaded WASM
variant — `@miden-sdk/miden-sdk/mt` (or `/mt/lazy`) and `@miden-sdk/react/mt`
(or `/mt/lazy`). All four entry points exist in both packages' `exports` maps.
The MT build uses `wasm-bindgen-rayon` and `SharedArrayBuffer` /
`WebAssembly.Memory({ shared: true })` for ~3–5x faster local proving.

**1. The page must be cross-origin-isolated** (COOP `same-origin` + COEP
`require-corp`). Without those headers the browser refuses to construct
`WebAssembly.Memory({ shared: true })` and the MT WASM fails to instantiate at
SDK load. `midenVitePlugin({ crossOriginIsolation: true })` covers the Vite dev
and preview servers only — see Production Deployment Headers.

**2. You must bring up the rayon thread pool yourself.** Every MT entry
re-exports `initThreadPool(n)` from `wasm-bindgen-rayon`. **The React SDK does
NOT call it for you.** Skip it and rayon spawns zero workers, every
`par_iter(...)` falls through to a sequential loop, and you have paid the full
COOP/COEP deployment cost to prove single-threaded anyway.

```typescript
import { MidenClient, initThreadPool } from "@miden-sdk/miden-sdk/mt/lazy";

await MidenClient.ready();
await initThreadPool(navigator.hardwareConcurrency); // once, at startup
```

Under React, gate it on readiness inside the provider tree:

```tsx
import { useEffect } from "react";
import { MidenProvider, useMiden } from "@miden-sdk/react/mt/lazy";
import { initThreadPool } from "@miden-sdk/miden-sdk/mt/lazy";

function ThreadPoolBoot() {
  const { isReady } = useMiden();
  useEffect(() => {
    if (!isReady) return;
    void initThreadPool(navigator.hardwareConcurrency);
  }, [isReady]);
  return null;
}
```

`initThreadPool` is idempotent — calling it again resolves with the existing
pool. The ST entries do not expose it (there is no thread pool to bring up).

If your app must host third-party iframes, OAuth popups, or other cross-origin
resources that don't emit `require-corp`, stay on the default ST imports and
leave `crossOriginIsolation: false` — you keep a fully working Miden client and
only forgo MT-accelerated local proving. Enabling `crossOriginIsolation: true`
also breaks OAuth-popup flows (e.g. Para), because `same-origin` COOP nullifies
`window.opener` in popups; this is the plugin's own stated reason for defaulting
the option to `false`.

## What midenVitePlugin() Handles

`@miden-sdk/vite-plugin` abstracts Miden-specific Vite configuration. It only
implements the `config` and `configResolved` hooks — it does **not** register a
`.wasm` module loader, because Vite's built-in handling does the actual `.wasm`
import. What the plugin sets up:

- **WASM dedup / single copy** — `resolve.alias` (an exact-match `^<pkg>$`
  regex, so subpath imports like `/lazy` still resolve through the package's
  `exports` map), `resolve.dedupe`, and `resolve.preserveSymlinks: true` force a
  single resolved copy of each entry in `wasmPackages`. The alias replacement is
  computed with `require.resolve` for pnpm / Yarn PnP portability. The dedupe
  list is `[...wasmPackages, "react", "react-dom", "react/jsx-runtime",
  "@miden-sdk/react"]`
- **optimizeDeps.exclude** — excludes `wasmPackages` from pre-bundling
  (pre-bundling corrupts the WASM binary)
- **Top-level await** — sets `build.target: "esnext"`, and in `configResolved`
  also forces `optimizeDeps.esbuildOptions.target = "esnext"`
- **ES-module workers** — sets `worker.format: "es"` and
  `worker.rollupOptions.output.format = "es"`, required for the SDK's module
  workers
- **COOP/COEP headers (opt-in, MT only)** — guarded by
  `if (crossOriginIsolation)`; when enabled it emits `Cross-Origin-Opener-Policy:
  same-origin` + `Cross-Origin-Embedder-Policy: require-corp` on **both**
  `server.headers` and `preview.headers`
- **gRPC-web dev proxy** — when `rpcProxyTarget !== false && env.command ===
  "serve"`, proxies `rpcProxyPath` (default `/rpc.Api`) to `rpcProxyTarget` with
  `changeOrigin: true`, to bypass CORS in dev
- **React context dedup** — an `externalize-miden-react` esbuild plugin pushed
  into `optimizeDeps.esbuildOptions.plugins` marks `@miden-sdk/react` external
  during pre-bundling, so signer-provider React contexts share one identity

The `configResolved` hook re-applies the esbuild plugin, the esnext target, and
the dedupe entries *after* all plugins' `config` hooks have merged, so other
plugins (e.g. `vite-plugin-node-polyfills`) can't overwrite them.

You don't need to install or configure `vite-plugin-wasm`,
`vite-plugin-top-level-await`, or dexie aliases manually.

## Required Dependencies

At `0.16.0-rc.7`, `@miden-sdk/miden-sdk`, `@miden-sdk/react`, and
`@miden-sdk/vite-plugin` all publish at the same version. Pin them exactly:

```json
{
  "dependencies": {
    "@miden-sdk/miden-sdk": "0.16.0-rc.7",
    "@miden-sdk/react": "0.16.0-rc.7"
  },
  "devDependencies": {
    "@miden-sdk/vite-plugin": "0.16.0-rc.7"
  }
}
```

Notes:

- **These are prerelease versions, and npm range syntax does not match
  prereleases.** `"0.16"`, `"^0.16.0"`, `"~0.16.0"` and `"0.16.x"` will NOT
  resolve to `0.16.0-rc.7` — they either fail to resolve or silently drift to a
  later stable line. Use the exact string, or the caret-on-a-prerelease form
  `"^0.16.0-rc.7"` that the in-repo example
  (`packages/react-sdk/examples/wallet/package.json`) uses.
- **`@miden-sdk/react` and `@miden-sdk/miden-sdk` must match.** The React SDK's
  peer dependency is `"@miden-sdk/miden-sdk": "^0.16.0-rc.7"`, and the repo
  enforces the coupling in CI. Per its `README.md`: "A repo-wide
  `scripts/check-react-sdk-sync.js` enforces that React peer ranges and example
  dependencies pin to the exact patch version of the WASM client they were
  built against." Upgrade them together.
- **The vite-plugin still carries its own version field.** It happens to match
  the core SDK at this pin, but it is released through a separate gate
  (`scripts/check-vite-plugin-version-release.sh` publishes it only when its
  local `package.json` version is not already on npm), so it can drift between
  releases. Always defer to your app's `package.json` rather than assuming
  `vite-plugin === miden-sdk`.
- **The wallet adapter lives in a separate repo.** The example app imports
  `MidenFiSignerProvider` from `@miden-sdk/miden-wallet-adapter-react`, which is
  published from [`0xMiden/miden-wallet-adapter`](https://github.com/0xMiden/miden-wallet-adapter),
  not the web-sdk repo. Confirm its version against that repo or your app's
  `package.json`.
- **When you bump, do a clean install with the package manager the project
  actually uses.** The web-sdk itself is pnpm-only (`rm -rf node_modules
  pnpm-lock.yaml && pnpm install`); the example app declares
  `packageManager: "pnpm@9.15.4"` with `engines.node >= 20` and
  `engines.pnpm >= 9`.

## The Web Worker Shim (`useWorker`)

By default the SDK spawns a Web Worker and runs WASM calls off the main thread
(`ClientOptions.useWorker` defaults to `true`). This matters for a Vite app
because the worker is loaded via `new Worker(new URL(...), { type: "module" })`,
which is why the plugin sets `worker.format: "es"`.

Set `useWorker: false` when:

- You pass a `CallbackProver` via `TransactionProver.newCallbackProver(jsFn)`.
  The worker boundary serializes the prover with `TransactionProver.serialize()`,
  which has no encoding for the callback variant and silently downgrades it to
  `"local"` — your callback would never fire.
- You embed the client in a single-WebView native shell (Capacitor host, Tauri,
  Electron preload), where the UI thread isn't competing with the WASM thread
  anyway.

`MidenProvider` forwards `config.useWorker` straight into
`WebClient.createClient(...)` / `WebClient.createClientWithExternalKeystore(...)`,
so React consumers set it on the provider config.

## Production Deployment Headers

These headers apply **only if you ship the MT WASM variant** (`/mt` or
`/mt/lazy`). The default ST build needs none of this. If you are on MT, the
COOP/COEP headers must be set on the production server:
`midenVitePlugin({ crossOriginIsolation: true })` only emits them on the Vite dev
server (`vite`) and the Vite preview server (`vite preview`) — it does not touch
your real production host.

`crates/web-client/README.md` ("Setting cross-origin isolation headers") is the
maintained reference and covers more hosts than the snippets below, including
Next.js (`next.config.mjs` `headers()`), Express / generic Node
(`res.setHeader`), and MV3 browser-extension manifests
(`"cross_origin_opener_policy": { "value": "same-origin" }`).

### Nginx
```nginx
add_header Cross-Origin-Opener-Policy same-origin;
add_header Cross-Origin-Embedder-Policy require-corp;
```

### Vercel (vercel.json)
```json
{
  "headers": [
    {
      "source": "/(.*)",
      "headers": [
        { "key": "Cross-Origin-Opener-Policy", "value": "same-origin" },
        { "key": "Cross-Origin-Embedder-Policy", "value": "require-corp" }
      ]
    }
  ]
}
```

### Cloudflare Pages (_headers)
```
/*
  Cross-Origin-Opener-Policy: same-origin
  Cross-Origin-Embedder-Policy: require-corp
```

## COOP/COEP Gotchas

These apply only once you've enabled cross-origin isolation for the MT build —
the default ST build sets no such headers and is unaffected. `require-corp`
blocks any cross-origin resource (images, fonts, iframes, scripts) that doesn't
carry `Cross-Origin-Resource-Policy: cross-origin` or appropriate CORS. In
practice that breaks:

- **Third-party iframes** (YouTube embeds, Twitter embeds, analytics)
- **External scripts** without CORS headers
- **OAuth popups** from different origins (COOP `same-origin` nullifies
  `window.opener`)

Treat it as a deployment decision and opt in only when you understand your
page's resource graph.

If you cannot set the headers at all (CDN, hosting provider that doesn't allow
header injection), the documented escape hatch is the COI service-worker shim
pattern (`gzuidhof/coi-serviceworker`): a small same-origin service worker
intercepts fetches and re-injects the headers on the way back. The SDK
deliberately does not bundle it, because installing a service worker into a
consumer's app is intrusive — adopt it consciously.

## TypeScript Compatibility

Standard Vite-compatible tsconfig settings work with Miden. The real constraint
is an ES2020+ target, because the SDK's public types use `bigint` (asset
amounts, `Felt` values, and every `JsU64` return are JS `BigInt`s). The shipped
example's tsconfig is the reference:

```json
{
  "compilerOptions": {
    "target": "ES2020",
    "lib": ["ES2020", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "moduleResolution": "bundler",
    "useDefineForClassFields": true,
    "jsx": "react-jsx",
    "isolatedModules": true,
    "strict": true,
    "noEmit": true
  }
}
```

`module: "ESNext"` and `moduleResolution: "bundler"` are standard Vite defaults,
not Miden-specific requirements. If you're using the Vite-generated tsconfig, no
changes are needed beyond ensuring `target` is ES2020+.

## Troubleshooting

| Issue | Cause | Fix |
|-------|-------|-----|
| "SharedArrayBuffer is not defined" (MT build only) | Importing `/mt` or `/mt/lazy` on a page that isn't cross-origin-isolated | Set `midenVitePlugin({ crossOriginIsolation: true })` and add the COOP/COEP headers on your production host; or switch back to the default ST imports, which don't need them |
| MT build is no faster than ST | `initThreadPool(n)` was never awaited, so rayon has zero workers | `await initThreadPool(navigator.hardwareConcurrency)` once at startup — nothing else calls it for you |
| WASM module not found | SDK not configured correctly | Ensure `midenVitePlugin()` is in the plugins array |
| "Top-level await not supported" | Missing plugin setup | Ensure `midenVitePlugin()` is in the plugins array (it sets `build.target: "esnext"` and the esbuild target) |
| Module evaluation hangs on load (Capacitor WKWebView, Next.js SSR) | The default eager entry awaits WASM at module top level; TLA blocks SSR module evaluation and hangs in Capacitor's `capacitor://localhost` scheme handler | Import `@miden-sdk/miden-sdk/lazy` (no top-level await) and `await MidenClient.ready()` before touching any wasm-bindgen constructor |
| WASM init hangs in the browser | COEP blocking the WASM fetch | Check the network tab for blocked requests; verify the COOP/COEP headers are actually present |
| "recursive use of an object" | Concurrent WASM access | Use `runExclusive()` from `useMiden()` |
| Double initialization in dev | React StrictMode | Use `MidenProvider` (it queues init through `runExclusive` and handles the StrictMode double mount internally) |
| A VM assertion failure reports only an error code, no message | Production builds strip MASM debug metadata (source spans and `assert.err` text) from the embedded Miden packages, cutting the ST binary from 27.4 MB to 18.8 MB | Reproduce against a dev build (`MIDEN_WEB_DEV=true`), which keeps full diagnostics |
