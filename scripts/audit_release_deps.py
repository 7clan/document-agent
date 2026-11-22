"""Audit installed runtime and Windows lock; preserve exact tool findings.

Security findings are never silently reclassified as successes.
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / ".local" / "security"
OUT.mkdir(parents=True, exist_ok=True)


def audit(label: str, args: list[str], timeout: int = 240) -> dict:
    output = OUT / (label + "_pip_audit.json")
    try:
        run = subprocess.run(
            ["pip-audit", "-f", "json", "-o", str(output), "--progress-spinner", "off",
             *args], check=False, capture_output=True, text=True, timeout=timeout,
        )
        payload = json.loads(output.read_text(encoding="utf-8")) if output.exists() else {}
        deps = payload.get("dependencies", []) if isinstance(payload, dict) else []
        vulnerable = [
            {"name": entry.get("name"), "version": entry.get("version"),
             "vulns": [{"id": item.get("id"), "fix_versions": item.get("fix_versions", [])}
                       for item in entry.get("vulns", [])]}
            for entry in deps if entry.get("vulns")
        ]
        return {"exit_code": run.returncode, "scanned_packages": len(deps),
                "affected_packages": len(vulnerable),
                "advisories": sum(len(x["vulns"]) for x in vulnerable),
                "findings": vulnerable,
                "tool_error": run.stderr.strip()[:600] if run.returncode not in (0, 1)
                              or not deps else ""}
    except Exception as exc:  # noqa: BLE001
        return {"tool_error_type": type(exc).__name__, "tool_error": str(exc)[:300]}


def main() -> int:
    check = subprocess.run(
        [sys.executable, "-m", "pip", "check"], check=False, capture_output=True, text=True,
    )
    report = {
        "created_utc": datetime.now(UTC).isoformat(),
        "pip_check_exit": check.returncode,
        "pip_check_excerpt": check.stdout.strip()[:500],
        "linux_installed": audit("linux_installed", ["--local"]),
        # Review pinned Windows dependency versions even though this CI runner
        # is Linux. The requirements lock is pin-only, not hashes.
        "windows_lock_pinned": audit(
            "windows_lock_pinned", ["-r", str(ROOT / "requirements.lock"), "--no-deps", "--disable-pip"]),
    }
    report["release_pass"] = (
        check.returncode == 0
        and all(entry.get("exit_code") == 0
                and entry.get("affected_packages") == 0
                for entry in (report["linux_installed"], report["windows_lock_pinned"]))
    )
    (OUT / "security_summary.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print("SECURITY SUMMARY " + json.dumps({
        "passed": report["release_pass"],
        "pip_check": report["pip_check_exit"],
        "linux_installed_affected": report["linux_installed"].get("affected_packages"),
        "windows_lock_affected": report["windows_lock_pinned"].get("affected_packages"),
        "windows_pillow_findings": [
            x for x in report["windows_lock_pinned"].get("findings", [])
            if x.get("name", "").lower() == "pillow"
        ],
        "audit_errors": [
            entry.get("tool_error") for entry in (
                report["linux_installed"], report["windows_lock_pinned"])
            if entry.get("tool_error")
        ],
    }), flush=True)
    return 0 if report["release_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
