# Inert executable-allowlist transaction backend

No import registers a tool, discovers a DataRoot, loads a key, enrolls authority,
or changes installed policy. Keep management RPC off model-discoverable routes.
This is source plus disposable Windows evidence, **not live activation**.

## Concrete internal integration API

`AllowlistService(engine).dispatch(method, arguments, trusted_metadata)` is async.
The authenticated private adapter owns method mapping and supplies the actual
`TrustedMetadata` type from `app.core.execution_context`, not a model dictionary.
Closed arguments and results:

| method | arguments | result |
|---|---|---|
| list | `{}` | `{revision, allowed_executables}` |
| prepare | `{payload, session_id}` | shared challenge object |
| backup | `{operation_id}` | shared sealed preimage envelope |
| commit | `{operation_id, approval, backup_receipt}` | exact operation outcome |
| operation | `{operation_id}` | exact authenticated operation outcome |

`payload` is exactly `{action,target_profile_id,executable}` for add/remove or
`{action,target_profile_id,old_executable,new_executable}` for replace. Nothing
accepts policy paths, full policies, roots, limits, tools, capabilities, caller
identity, approved booleans or arbitrary metadata in arguments. The prepare
session must equal the independently resolved real broker/chat runtime session.
Do not substitute deterministic Files owner/resource session identifiers.

Construct `AllowlistEngine(policy_path, profiles_path, journal_dir,
enrollment=enrollment)` using fixed owner-loaded private paths. All three paths
and the parent directories must have reviewed owner/service-only ACLs and reside
outside ordinary Files roots. They must not be selected from RPC arguments.
Co-host with the real profile administration `LEASES` object. Default commit uses
its write lease, so already admitted managed commands finish before mutation;
ordinary command authorization already revalidates policy before launch.
Production must have one authoritative service process. External/offline profile
writers require the existing owner-local stopped-service boundary. The policy
writer additionally holds a Windows interprocess byte lock; a busy writer is a
static failure, not a retry or permission escalation.

Only the reviewed owner loader calls
`authority._enrollment_from_owner_loader(authority._INTERNAL, placement=...,
actions=frozenset(...), key_id=..., approval_key=Ed25519PublicKey,
backup_key=X25519PublicKey, capability_revision=..., current=...)`.
The inert `owner_loader.py` implements validation of this supplied enrollment;
it does not provision it or authorize enrollment. The explicit
capability is `executable_allowlist_management`, distinct from profile management
and every ordinary Files/command scope. `current(context)` MUST re-read dedicated
authority, placement, revocation and owner enrollment and return exactly `True`.
A truthy object is denied. Python markers are a typed internal boundary, not
isolation from arbitrary same-process Python or an OS-owner/root-capable model.

Trusted metadata has exactly one authority member at
`zagent.executable_allowlist_management_context`; its body has exactly:
`principal_id, workspace_id, device_id, installation_id, target_profile_id,
capability_revision, profile_generation, session_id, actor_user_id, chat_id,
thread_id, deadline`. Profile generation is the real catalog's string token.
The trusted adapter must bind actor/chat/topic to the enrolled broker, not copy
these fields from caller metadata or an ordinary execution context.
Only the adapter constructs `_context_from_enrolled_adapter` internally; the
service does this per call and every engine method revalidates current authority.

## Wire compatibility and confidential backup

The shared peer contract is described in
`docs/REMOTE-ALLOWLIST-ADMINISTRATION-CONTRACT.md` and the inactive VPS plugin.
Challenge keys are exactly protocol `METADATA` plus `profile_generation,
session_id, action, nonce, iat, exp, placement_risk`. IDs are lowercase uuid32,
nonce is unpadded base64url32, challenge TTL is at most 240 seconds. Receipts
permit at most 300 seconds and bind full placement, operation, raw-byte revision,
payload, session, profile generation, nonce, exact rule digest and human route.

The pinned Ed25519 signing key and independent X25519 transport-encryption key
are supplied by owner bootstrap. The VPS separately owns the at-rest AES key.
**Backup receipt `backup_digest` is the VPS ciphertext SHA256, NOT the preimage
SHA256.** Its authenticated `expected_revision` already binds the raw preimage.
The VPS must durably store, read back and decrypt-verify before signing a receipt,
and enforce 30-day retention. Windows verifies signature, metadata and retention;
it cannot itself prove a malicious trusted signer durably stored ciphertext.
Never use a generic model-visible Files tool or exception-logging probe for the
secret backup/commit channel. Adapter errors must be sanitized static failures.

Preimage plaintext is bounded memory only. Sealing is ephemeral X25519,
HKDF-SHA256 with salt `sha256(canonical(metadata))`, info
`zagent.allowlist.backup.v1`, AES256GCM nonce12 and canonical metadata AAD.
Only the bounded candidate and encrypted preimage are pending in memory.
Publication creates a transient candidate, never a retained laptop preimage.
Python bytes are not guaranteed zeroized; ACLs are not root/model isolation.

## Transactions and uncertainty

Engine-internal `prepare(context,payload,expected_revision=None,
idempotency_key=None)` supports exact owner-scoped idempotency. The narrow peer
facade uses a fresh generated operation ID; prepare itself never mutates policy.
An identical explicit key/payload/revision/context fingerprint returns the same
operation; changed reuse is rejected. Journal records contain only closed-schema
metadata, challenge, hashes, state and sanitized outcome, never policy bodies,
path payloads, signed receipts, signing/decryption keys or tokens.

New executable literals must be existing absolute physical Windows `.exe` files,
including every ancestor; reject UNC/device/ADS/env/PATH/reparse/8.3 aliases and
casefold duplicates. Existing stale old literals may be removed/replaced by exact
match without requiring the old file to exist. Preserve list order, reject last
removal and enforce the real consumer's bounds and exact v1/v2 policy envelope.
No schema metadata or unrelated policy fields/siblings are changed.

Commit rechecks authority after lease wait and receipt round trip, catalog
generation, CAS revision, executable physical placement and receipt validity
immediately before publication. A metadata-only durable `committing` intent
precedes `os.replace`, followed by exact byte readback. Exceptions after intent
are not safely retryable: query **the same operation**. Recovery compares current
policy SHA256 with candidate/preimage; candidate means applied, preimage means
failed, any third revision remains uncertain and blocks new mutations until
owner review. A restarted pending operation cannot reconstruct its candidate or
sealed backup; it cannot commit without the original in-memory pending object
and expires rather than re-creating confidential state or blindly retrying.
Journal capacity (4096 records) fails closed and needs owner archival; pending
memory is bounded (32 operations). There is no automatic history deletion.

## Evidence and remaining gates

Run from `agents/files/engine` with the approved Files interpreter:
`python -m pytest tests/test_allowlist_protocol.py tests/test_allowlist_engine.py tests/test_allowlist_adversity.py -q`.
Fixtures use synthetic temp policies, ephemeral test keys and actual Windows
atomic replacement, byte locking in a second approved Python process, Win32
junction rejection, real consumer authorization/resolution, both v1/v2 schemas,
CAS/replay/idempotency, lease waiting/revocation, stale old paths and interrupted
publication/restart recovery. They never locate the installed private policy.

NOT_RUN here: live enrollment, live Telegram callback, live encrypted VPS backup,
production key custody/ACL validation, backup retention scheduler, power-loss
filesystem durability, and live end-to-end mutation plus harmless execution.
Nothing was exposed, enabled, restarted, committed or pushed by this module.

## Private authenticated adapter and owner loader — not mounted

`load_owner(OwnerConfiguration(...), oauth_current=..., resolve_runtime=...)`
returns a `LoadedOwner` only after checking the actual Windows process SID,
private source/policy/catalog/journal/replay/key paths and their native DACLs,
all ancestors, reparse points, raw public-key byte pins, exact placement/actions,
local capability revision, expiry and revocation. Paths must be pre-existing
absolute descendants of the trusted DataRoot. The actual catalog must not expose
that DataRoot. Public roots are checked for reparse ancestors and compared by
physical resolution, not lexical spelling alone. Native `pywin32` and
`cryptography` must already be available; missing APIs fail closed.

`OwnerConfiguration` is a trusted startup API, never a request schema. It has
fixed `data_root, source_path, policy_path, profiles_path, journal_dir, replay_dir,
approval_key_path, backup_key_path, request_key_path`, actual `owner_sid` and
`service_sid`, exact placement/actions/key IDs/capability revision and three raw
public-key SHA256 pins. It creates no key, enrollment, directory or grant.
The separate version-1 source document has exactly `version, capability,
placement, actions, key_id, request_key_id, capability_revision, expires_at,
revoked`. It is a new explicit source format, not a claim that Core already
provisions this capability. Ordinary Files metadata and its internal token do
not enroll this source.

`oauth_current(fields)` must independently query the currently enrolled dedicated
authority and return exactly `True`, not a truthy value. `resolve_runtime(fields)`
must return exactly the currently active `session_id, profile_generation,
actor_user_id, chat_id, thread_id` from a trusted runtime source. Echoing the
request's fields is not an implementation. Supplying real host callbacks and
out-of-band public-key enrollment remains a production integration gate. Test
lambdas and ephemeral keys are fixtures, not substitutes for these callbacks.
Every engine authorization rechecks the source, pins, paths and callbacks.

`make_private_app(owner)` returns an **unregistered ASGI HTTP app**. It does not
bind a port, mount a route, register an MCP tool, enable a capability or alter
Core/Files startup. It dispatches outside the generic Files read lease, while
the real engine acquires the shared profile-administration write lease for
commit. This avoids read-to-write self-deadlock. Production hosting, HTTPS,
trusted callback wiring and approved lifecycle changes are still NOT_RUN.

The app accepts only POST `/` with a closed request:
`{version,kind,key_id,body,signature,arguments}`. `kind` is
`zagent.allowlist.dispatch.v1`; the Ed25519 signature covers canonical
`{version,kind,key_id,body}`. Body is exactly `method, arguments_sha256, context,
nonce, iat, exp, audience`; arguments are bound by their canonical SHA256.
Audience is `zagent.allowlist.private-dispatch`, nonce is base64url32 bytes,
and integer validity is at most 60 seconds. Context is the exact authority body
above and its deadline may not exceed request expiry. Attestation uses an
explicit pinned broker request key; it is **not** human approval or a backup
receipt. The normal independent signed approval and backup receipt remain
mandatory at commit. Keep request signing separate from approval signing.

Replay nonces are exclusive-create/fsync claims in the protected replay directory
and survive app reconstruction. Capacity is 4096 claims; no automatic history
deletion is provided. Owner archival must not reaccept outstanding requests.
HTTP error bodies are always `ALLOWLIST_REQUEST_DENIED`, without private paths,
keys, upstream exceptions or request contents. Direct Python APIs are internal,
not public error surfaces. Same-owner arbitrary Python/root-capable agent access
is not isolated by these checks.

## Expanded verification evidence

Coordinator Windows command:
`python -m pytest tests/test_allowlist_protocol.py tests/test_allowlist_engine.py tests/test_allowlist_adversity.py tests/test_allowlist_process_crash.py tests/test_allowlist_adapter.py -q --tb=short`
returned **114 passed, exit 0** (task
`tsk_0a7eb314ad424e90ae8015e6965df234`). This includes 50 adapter/loader fixtures
with real Windows DACLs, junction rejection, HTTP attestation/replay/denials,
full prepare/backup/commit/exact-status dispatch and real shared-lease waiting,
revocation and cancellation. Five process-termination fixtures use actual Windows
TerminateProcess at publication checkpoints. A crash before policy replacement
can retain a bounded candidate file; the fixtures inspect its intended hash/size.
No automatic candidate cleanup or power-loss guarantee is claimed.

Actual peer cryptography across VPS and Windows was separately checked with
synthetic data by the coordinator's profile-local
`zagent-implementation/verify_allowlist_peer_interop.py` (six assertions).
HTTP fixtures use ephemeral synthetic receipts, not installed policy or a live
Telegram decision. Production key custody/ACL acceptance, real host callbacks,
route mounting, scheduled VPS retention and live end-to-end approval remain
NOT_RUN. No installed private configuration, policy or live route was changed.
