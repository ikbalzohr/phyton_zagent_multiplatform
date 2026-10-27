# Existing owner command-policy migration

This is an explicit installation-owner operation, not an MCP tool or a way to
approve arbitrary executables. It moves one existing approved command entry to
the already approved `agentRoot` at `D:\3-Ikbalzohr\Agent`. It never duplicates
an entry or edits executables, tools, timeout/output limits, OAuth, grants, or
profiles.json. Root rebinding changes the approved working-directory placement;
it does not sandbox owner-account interpreters. These retain owner-account OS access.

## Inspect first (Windows owner console)

Stop Core (closing its browser is insufficient) and any dotnet hosts first.
Use the enrolled install directory and DataRoot, after pulling `zagent-v1`:

```powershell
.\packaging\scripts\Rebind-OwnerCommandPolicy.ps1 `
  -InstallRoot 'D:\3-Ikbalzohr\Agent\phyton_zagent_multiplatform' `
  -DataRoot 'C:\Users\fazrin\AppData\Local\Zagent-Local' `
  -InspectOnly
```

Expected `INSPECT_ONLY`, `writes: 0`. The output projects policy bindings and
execution limits only, not secrets or unrelated configurations. This does not
prove executables exist or that command authorization will pass. Both modes
check the private ACLs, enrolled install/DataRoot binding and stopped Core.

## Apply after verifying the exact source

Pass the exact `profile_id` and `root` returned by inspection. Do not guess them.
For an intentionally removed source catalog row, add `-AllowRemovedSourceProfile`.
This flag does not bypass validation when the source row still exists and is
disabled, read-only or unauthorized. The existing source execution policy must
remain enabled, owner-account and explicitly acknowledged in either case.

```powershell
# Replace both placeholders with the inspected exact values before executing.
.\packaging\scripts\Rebind-OwnerCommandPolicy.ps1 `
  -InstallRoot 'D:\3-Ikbalzohr\Agent\phyton_zagent_multiplatform' `
  -DataRoot 'C:\Users\fazrin\AppData\Local\Zagent-Local' `
  -SourceProfileId '<inspected-source-id>' `
  -SourceRoot '<inspected-source-root>' `
  -AllowRemovedSourceProfile
```

v1 edits the existing entry. v2 renames its map key and embedded profile_id
without retaining a duplicate source entry. Reverse edits must reproduce every
original byte. Existing agentRoot policy conflicts fail closed; rerunning apply
is not a blind retry mechanism. Inspect current state first if a result is uncertain.

Publication uses one atomic replacement with a unique private backup. Its exact
contents and the new file are read back; machine/profile/policy snapshots and
candidate bytes are checked before publishing. Any failure after replacement
requires inspection with Core stopped; no automatic rollback or retry occurs.
Success emits `PROFILE_COMMAND_POLICY_REBOUND` and leaves Core stopped.

After restart, separately verify `files_command_capabilities` and one harmless
command using an already approved executable. Do not add interpreters to make a
test pass. If refused, diagnose the specific next gate rather than weakening it.

## Verification boundaries

```sh
python3 tests/check_owner_command_policy_rebind.py
```

This invokes the real pure PowerShell planner, then passes its output through
AST-isolated `_policy_profiles` and `_POLICY_KEYS` from managed_commands.py.
It compares every unchanged policy field and sibling. No product imports,
Windows ACL, Windows atomic replacement, enrollment, or live command execution
are exercised by that test. Source guards for the offline wrapper are not Windows
runtime acceptance. Windows apply remains NOT_RUN until executed by the owner.
