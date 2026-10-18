import sys
from .ipc_client import send_command, ArcMapBridgeError
from .safety import SafetyPolicy


def main():
    print("=" * 58)
    print("ZAGENT ARCMAP - PREFLIGHT")
    print("=" * 58)
    print("Python:", sys.version.split()[0])
    print("Safety:", SafetyPolicy().status())
    try:
        result = send_command("ping", timeout=3)
    except ArcMapBridgeError as exc:
        print("STATUS: NOT READY")
        print("ERROR:", exc)
        return 2
    print("ArcMap:", result.get("status"))
    print("MXD:", result.get("mxd"))
    print("Bridge actions:", result.get("bridge_action_count"))
    print("Stage 2 bridge actions:", result.get("stage2_bridge_action_count"))
    print("Stage 2 bridge loaded:", result.get("stage2_bridge_loaded"))
    print("STATUS: READY" if result.get("ok") else "STATUS: NOT READY")
    return 0 if result.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
