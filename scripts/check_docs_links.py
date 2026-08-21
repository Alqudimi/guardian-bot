from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MARKDOWN = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
errors: list[str] = []

for source in ROOT.rglob("*.md"):
    if ".git" in source.parts:
        continue
    text = source.read_text(encoding="utf-8")
    for raw_target in MARKDOWN.findall(text):
        target = raw_target.split("#", 1)[0].strip()
        if not target or target.startswith(("http://", "https://", "mailto:", "tel:")):
            continue
        candidate = (source.parent / target).resolve()
        try:
            candidate.relative_to(ROOT.resolve())
        except ValueError:
            errors.append(f"{source.relative_to(ROOT)} -> outside repository: {target}")
            continue
        if not candidate.exists():
            errors.append(f"{source.relative_to(ROOT)} -> missing: {target}")

if errors:
    print("documentation link check failed")
    print("\n".join(errors))
    raise SystemExit(1)

print(f"documentation link check passed: {sum(1 for _ in ROOT.rglob('*.md'))} markdown files")
