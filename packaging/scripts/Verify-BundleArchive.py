"""Standalone read-only verification of Zagent RC bundle; never executes installer."""
import hashlib
import json
import os
from pathlib import Path
import struct
import sys
import zipfile

bundle = Path(sys.argv[1]).resolve()
stem = bundle.stem
metadata = json.loads(bundle.with_suffix(".json").read_text(encoding="utf-8-sig"))
zip_path = bundle.with_name(stem + ".payload.zip")
manifest_path = Path(sys.argv[2]).resolve()
required = (
    "Zagent.Core.exe",
    "Zagent.Manager.exe",
    "Zagent.Setup.exe",
    "agents/web/engine/dist/bridge/Bridge.js",
    "agents/web/engine/dist/tools/bridge.js",
    "agents/web/engine/extension/background.js",
    "agents/web/engine/extension/popup.html",
    "agents/web/engine/extension/popup.js",
    "agents/web/engine/extension/popup.css",
    "agents/arcmap/engine/arcmap_bridge/core/smart_corner_geometry.py",
    "agents/arcmap/engine/arcmap_bridge/features/smart_corner.py",
    "agents/arcmap/engine/mcp_server/tools/smart_corner.py",
    "agents/arcmap/engine/arcmap_bridge/features/native_layer_properties.py",
    "agents/arcmap/engine/arcmap_bridge/features/native_grids.py",
    "agents/arcmap/engine/mcp_server/window_capture.py",
    "agents/arcmap/engine/mcp_server/tools/arc_backlog.py",
    "agents/arcmap/engine/arcmap_bridge/core/concurrent_edit_guard.py",
    "agents/arcmap/engine/arcmap_bridge/features/native_label_preset.py",
    "agents/arcmap/engine/arcmap_bridge/features/gis_server_connector.py",
    "agents/arcmap/engine/arcmap_bridge/features/native_scale_bar.py",
    "agents/arcmap/engine/arcmap_bridge/features/concurrent_edit.py",
    "agents/arcmap/engine/arcmap_bridge/features/calculate_geometry.py",
    "agents/arcmap/engine/arcmap_bridge/features/smart_coordinate_importer.py",
    "agents/arcmap/runtime-tools.snapshot.json",
    "agents/arcmap/arcmap.component.json",
    "payload-manifest.json",
)


def sha256_of(path):
    result = hashlib.sha256()
    with open(path, "rb") as stream:
        while True:
            chunk = stream.read(1024 * 1024)
            if not chunk:
                break
            result.update(chunk)
    return result.hexdigest()


def assert_equal(label, observed, expected):
    if observed != expected:
        raise AssertionError(f"{label}: expected={expected!r}, actual={observed!r}")
    print("VERIFY_" + label + "=PASS")


assert_equal("INSTALLER_SHA256", sha256_of(bundle), metadata["installer_sha256"])
assert_equal("ZIP_SHA256", sha256_of(zip_path), metadata["payload_zip_sha256"])
assert_equal("MANIFEST_SHA256", sha256_of(manifest_path), metadata["payload_manifest_sha256"])
assert_equal("EXE_LENGTH", bundle.stat().st_size, metadata["installer_size_bytes"])
with open(bundle, "rb") as stream:
    stream.seek(-32, os.SEEK_END)
    footer = stream.read(32)
    assert_equal("FOOTER_MAGIC", footer[:16], b"ZAGENTBUNDLE0001")
    stub_offset, zip_length = struct.unpack("<QQ", footer[16:])
    assert_equal("STUB_BYTES", stub_offset, metadata["stub_size_bytes"])
    assert_equal("EMBEDDED_ZIP_BYTES", zip_length, zip_path.stat().st_size)
    assert_equal("EMBEDDED_FINAL_LENGTH", stub_offset + zip_length + 32, bundle.stat().st_size)
    stream.seek(stub_offset)
    digest = hashlib.sha256()
    remaining = zip_length
    while remaining:
        chunk = stream.read(min(1024 * 1024, remaining))
        if not chunk:
            raise AssertionError("Embedded ZIP truncated")
        digest.update(chunk)
        remaining -= len(chunk)
    assert_equal("EMBEDDED_ZIP_SHA256", digest.hexdigest(), metadata["payload_zip_sha256"])

with zipfile.ZipFile(zip_path, "r") as archive:
    names = archive.namelist()
    actual = set(names)
    if len(actual) != len(names):
        raise AssertionError("ZIP contains duplicate path entries")
    manifest = json.loads(archive.read("payload-manifest.json").decode("utf-8-sig"))
    assert_equal("ZIP_FILE_COUNT", len(actual), int(manifest["file_count"]) + 1)
    assert_equal("ZIP_MANIFEST_CONTENT", archive.read("payload-manifest.json"),
                 manifest_path.read_bytes())
    for name in required:
        if name not in actual:
            raise AssertionError(f"Required bundled source missing: {name}")
    print("VERIFY_REQUIRED_FILES=PASS")
    web_checks = {
        "agents/web/engine/dist/bridge/Bridge.js": ("persistentConsent", "approvedTargetIds", "targets-sync", "consent-upgrade"),
        "agents/web/engine/dist/tools/bridge.js": ("approved_persistent", "fresh-extension-heartbeat"),
        "agents/web/engine/extension/background.js": ("persistent-all-tabs-v1", "targets-sync", "consent-upgrade", "chrome.tabs.onCreated"),
        "agents/web/engine/extension/popup.js": ('act("approve")', 'act("disconnect")'),
    }
    for rel, tokens in web_checks.items():
        payload = archive.read(rel).decode("utf-8-sig")
        for token in tokens:
            if token not in payload:
                raise AssertionError(f"Chrome Bridge feature missing in bundle: {rel} {token}")
    popup = archive.read("agents/web/engine/extension/popup.html").decode("utf-8-sig")
    if 'id="approve"' not in popup or 'id="disconnect"' not in popup:
        raise AssertionError("Chrome Bridge Approve/Disconnect buttons missing")
    if 'id="pair"' in popup or 'id="authorize"' in popup:
        raise AssertionError("Legacy Chrome Bridge buttons found")
    print("VERIFY_CHROME_PERSISTENT_BRIDGE=PASS")
    s = json.loads(archive.read("agents/arcmap/runtime-tools.snapshot.json").decode("utf-8-sig"))
    arc = json.loads(archive.read("agents/arcmap/arcmap.component.json").decode("utf-8-sig"))
    assert_equal("ARCMAP_DECLARED_TOOLS", int(s["count"]), 160)
    assert_equal("ARCMAP_COMPONENT_TOOLS", int(arc["public_tools"]["count"]), 160)
    entries = {e["path"]: e for e in manifest["files"]}
    for name in required:
        if name == "payload-manifest.json":
            continue
        info = entries[name]
        data = archive.read(name)
        assert_equal("FILE_SHA_" + Path(name).name,
                     hashlib.sha256(data).hexdigest(), info["sha256"])
        assert_equal("FILE_SIZE_" + Path(name).name,
                     len(data), int(info["size"]))
    # Validate CRC of *every* archive file without extraction to disk.
    assert_equal("ZIP_FULL_CRC", archive.testzip(), None)

print(f"VERIFIED_BUNDLE=PASS path={bundle} sha256={metadata['installer_sha256']}")
