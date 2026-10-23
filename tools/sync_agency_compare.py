"""Sync the skills-only package and skill references from agency-compare sources; --check exits 1 on drift."""
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1] / "untapped-agency-compare"
PRICE = re.compile(r"\$\d")  # the ChatGPT package bans prices (tools/build_chatgpt.py BANNED)


def without_prices(raw):
    """ChatGPT copy of futg_facts.json: drop every quote with a $ amount (Max, 2026-10-23); the plugin keeps them."""
    doc = json.loads(raw)
    for fact in doc["facts"].values():
        fact["candidates"] = [c for c in fact["candidates"] if not PRICE.search(c["quote"])]
        fact["status"] = "stated" if fact["candidates"] else "not stated"
    doc["approval"]["note"] += " ChatGPT copy: quotes with prices left out."
    return (json.dumps(doc, indent=1, ensure_ascii=False) + "\n").encode("utf-8")


def wanted(root=ROOT):
    data = json.loads((root / "data/criteria.json").read_text(encoding="utf-8"))
    criteria = "# Comparison criteria\n\nUse the same criteria for every agency. Priorities only change row order.\n\n"
    criteria += "\n\n".join(f'## {c["label"]} (`{c["id"]}`)\n\n{c["meaning"]}\n\nQuestion when not stated: {c["question"]}' for c in data) + "\n"
    skill = root / "skills/compare-agencies"
    facts = (root / "data/futg_facts.json").read_bytes()
    return {root / "chatgpt-skill/SKILL.md": (skill / "SKILL.md").read_bytes(),
            root / "chatgpt-skill/criteria.md": criteria.encode("utf-8"),
            root / "chatgpt-skill/futg_facts.json": without_prices(facts),
            skill / "criteria.md": criteria.encode("utf-8"), skill / "futg_facts.json": facts}


def main():
    check = "--check" in sys.argv
    drift = []
    for path, content in wanted().items():
        if not path.exists() or path.read_bytes() != content:
            drift.append(str(path.relative_to(ROOT)))
            if not check:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)
    if check and drift:
        print("Agency comparison skill drift: " + ", ".join(drift))
        return 1
    print("Agency comparison skill copies current." if check else "Synced agency comparison skill copies.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
