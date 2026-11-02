# Zagent Multi Platform — independent MCP-first architecture

**Source root:** `D:\3-Ikbalzohr\Agent\phyton_zagent_multiplatform`.

This is a **standalone product**. It is **not** Zagent Dev, Zagent Production, their plugin host, or their deployment lifecycle. A connected external Files tool may be used by a developer to edit the source, but that does not create a runtime dependency. Do not use existing Dev/Production installation paths, configuration, identities, approvals, fallback plugin audiences, or credentials as defaults for this product.

## Arsitektur target yang ditetapkan pengguna (otoritatif)

**Lihat [ARCHITECTURE_TARGET.md](ARCHITECTURE_TARGET.md) sebagai diagram dan kontrak desain utama.**

**ChatGPT / Claude / Hermes / klien MCP** → **HTTPS MCP + OAuth** (autentikasi, otorisasi, routing) → **Zagent Core — .NET 10** (lifecycle, dashboard web, supervision, registry) → **empat komponen utama di bawah Core: Tunnel (transport & task routing), Files (file & command execution), Web (browser automation), ArcMap (GIS & ArcPy)**.

Susunan ini menyatakan **lapisan sistem dan kepemilikan lifecycle**, bukan kewajiban bahwa setiap panggilan tool harus melewati hop HTTP .NET. Multi Platform independen dari Zagent Production, termasuk tunnel dan API key. Alamat `https://zagent.ikbalzohr.web.id/mcp` disiapkan untuk Multi Platform dan **pernah terhubung ke Hermes**; jangan salah menafsirkan fakta historis itu sebagai deployment multi-client yang sudah tervalidasi.

## Catatan implementasi yang ada saat ini (bukan pengganti arsitektur target)

Source saat ini menggunakan MCP Router Python di dalam modul Tunnel sebagai HTTP resource-server dan pembuka jalur ke MCP upstream, sedangkan Core .NET mengelola lifecycle/supervision/registry. Dalam praktiknya Router bisa memanggil agent internal tanpa menjadikan Core sebagai proxy HTTP untuk setiap `tools/call`. Ini kompatibel dengan **peran kendali sentral Core** yang digambarkan, tetapi jangan menggambar Router seolah berada di atas Core sebagai pemilik lifecycle produk.

Any standards-compatible MCP client (ChatGPT, Claude, Codex, Hermes and others) -> authenticated HTTPS remote MCP endpoint -> Python Tunnel Router (resource-server ingress) -> local MCP upstream Files / Web / ArcMap / optional QGIS. Core manages the Router and agents through its local lifecycle/supervisor/registry.

- Multiple clients are peers: never infer privilege from client names, model/provider, session labels, or plugin audience.
- OAuth issuer, resource audience, token introspection and per-owner scopes/tool grants are configured **for this product**; no cross-product fallback.
- Each agent's internal service URL and technical credentials are local and distinct from remote client OAuth.
- Device/installation UUID and trusted execution context are security placement metadata, **not installation roles**. Owner/operator aliases are not authorization grants.
- Persist durable task receipts and idempotency for interrupted calls; do not blindly replay uncertain effects.
- No `Primary/Secondary` or `Master/User` installation mode. New installation folder is `Zagent`; system resources are scoped to selected installation root.
- Existing machine config may contain a historical role field, but it is not a routing/authorization input and is not rewritten automatically.

## Reconciliation behavior

When the journal contains an **orphaned, started** task, the Router must not silently replay it or permit an unverified conflicting write. A new client can call `zagent_reconciliation_status` (requires current authenticated `files:read`) to inspect **its own** task IDs and recovery classifications without fetching the potentially unavailable Files catalog. It does not disclose other owners' task IDs or file arguments and cannot mutate jobs.

For an eligible read-only `files_search`, `zagent_task_recover` provides a two-phase, audited plan/apply, with strict auth and CAS. An uncertain write or unknown effect requires verified manual owner reconciliation; disabling the quarantine, deleting SQLite/WAL, or inventing success is prohibited. `RESOURCE_RECONCILIATION_REQUIRED` is a safety signal, not evidence that the service is damaged.

## Development boundary

Use disposable fixtures and source-local builds. Never restart, reconfigure, overwrite or migrate other installed Zagent products. No automatic commit, deployment, or installer promotion. Build/test success is not full remote-MCP interoperability acceptance; verify each client OAuth/PKCE, initialize, tools/list, authorized tools/call, task receipt and readback on a separately provisioned installation.
