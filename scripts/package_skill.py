#!/usr/bin/env python3
"""Build deterministic, allowlisted skill archives using only the standard library."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
from zipfile import ZIP_STORED, ZipFile, ZipInfo


ROOT = Path(__file__).resolve().parents[1]
RUNTIME_FILES = (
    "SKILL.md",
    "agents/openai.yaml",
    "references/design-notes.md",
    "references/ledger-contract.md",
    "references/progress-viewer.md",
    "scripts/handoff_guard.py",
    "scripts/handoff_tui.py",
)


def build(output: Path, root: Path = ROOT) -> list[Path]:
    skill = root / "skills" / "handoff"
    # Resolve and read every allowlisted source before creating any output.
    sources = [(name, (skill / name).read_bytes()) for name in RUNTIME_FILES]
    sources.append(("LICENSE", (root / "LICENSE").read_bytes()))
    output.mkdir(parents=True, exist_ok=True)
    archive = output / "handoff.zip"
    with ZipFile(archive, "w", compression=ZIP_STORED) as bundle:
        for name, data in sorted(sources):
            info = ZipInfo("handoff/" + name, date_time=(2020, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            bundle.writestr(info, data)
    upload = output / "handoff.skill"
    upload.write_bytes(archive.read_bytes())
    checksums = output / "SHA256SUMS"
    checksums.write_text(
        "".join(
            f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n"
            for path in (archive, upload)
        ),
        encoding="utf-8",
    )
    return [archive, upload, checksums]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "dist")
    args = parser.parse_args()
    for path in build(args.output):
        print(path)


if __name__ == "__main__":
    main()
