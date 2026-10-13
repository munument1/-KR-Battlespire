"""Reassemble the verified Preview 2 delta-only payload from Preview 1.

Input: public Preview 1 zip plus textual base64 delta components.
Does not use or embed any copyrighted original game files.
"""
import argparse
import base64
import hashlib
import json
import zipfile
from pathlib import Path


def sha(value):
    return hashlib.sha256(value).hexdigest()


def build(baseline: Path, folder: Path, output: Path):
    plan = json.loads((folder / "plan.json").read_text(encoding="utf-8"))
    if sha(baseline.read_bytes()) != plan["base_zip_sha256"]:
        raise ValueError("Published Preview 1 base ZIP differs from the verified base")
    if output.exists():
        raise ValueError("Refusing to overwrite target")
    injected = {}
    for entry in plan["entries"]:
        path = entry["archive_path"]
        if path in injected or path.startswith("/") or ".." in Path(path).parts:
            raise ValueError("Invalid delta archive name")
        blob = base64.b64decode("".join(
            (folder / piece).read_text(encoding="ascii")
            for piece in entry["chunks"]
        ), validate=True)
        if sha(blob) != entry["sha256"] or len(blob) != entry["uncompressed_bytes"]:
            raise ValueError("Delta component hash/size does not match " + path)
        injected[path] = blob
    with zipfile.ZipFile(baseline) as old:
        order = [name for name in old.namelist() if name not in plan["removed"]]
        order += [name for name in injected if name not in order]
        data = {name: injected[name] if name in injected else old.read(name) for name in order}
    manifest = json.loads(data["manifest.json"])
    assert manifest["version"] == plan["target_manifest_version"] == "0.1.0-preview2"
    assert manifest["steam_default_launch_supported"] is True
    assert manifest["runtime_legacy_rsc_controls_fixed"] is True
    assert len(manifest["files"]) == 40
    assert next(e["target_sha256"] for e in manifest["files"] if e["path"] == "GAME.EXE") == "83eedcad9906626bc14d00aa09e3359e9064417a543826977fb9a0ad75992df8"
    checksum = manifest.pop("bundle_id")
    assert sha(json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")) == checksum
    manifest["bundle_id"] = checksum
    for entry in manifest["files"]:
        for target in [entry] + entry.get("members", []):
            if "payload" in target:
                if sha(data[target["payload"]]) != target["payload_sha256"]:
                    raise ValueError("Payload checksum differs: " + target["payload"])
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for name in order:
            z.writestr(name, data[name])
    with zipfile.ZipFile(output) as verify:
        for name in order:
            assert verify.read(name) == data[name]
    print(json.dumps({
        "version": manifest["version"], "archive_entries": len(order),
        "changed_entries": sorted(injected), "bundle_id": checksum,
        "payload_sha256": sha(output.read_bytes()),
        "compiled_game_exe_expected": next(e["target_sha256"] for e in manifest["files"] if e["path"] == "GAME.EXE"),
    }))


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--baseline", type=Path, required=True)
    p.add_argument("--components", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    build(args.baseline, args.components, args.output)
