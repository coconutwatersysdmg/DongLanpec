"""Copy audited AI/data-space backends without secrets, histories or business UI.

Run only during development/build. Normal platform runtime uses the copies.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil

from platform_core.private_database import atomic_json

BASE = Path(__file__).resolve().parent
AI = BASE.parent
RULES = (
    (AI / "ai_xiangmuguanli", "project_agent"),
    (AI / "ai_tiaojianshuru", "condition_agent"),
    (AI / "ai_yuanjiandingyi", "elements_agent"),
    (AI / "ai_guankoudingyi", "nozzle_agent"),
    (AI / "ai_buguan", "tube_agent"),
    (AI.parent / "data_center_standalone" / "data_center", "data_center"),
)
EXCLUDED = {"tests", "tools", "docs", "output", "outputs", "artifacts", "legacy", "legacy_demo",
            "_vendor", "__pycache__", ".pytest_cache", "modules", "data", "venv", ".venv", "build", "dist", "backup"}
ALLOWED_TUBE = {"bundle", "db", "models.py"}


def main():
    vendor = BASE / "vendor"
    if vendor.exists():
        raise RuntimeError("vendor 已存在，拒绝覆盖；请先审查原副本。")
    copied = []
    for root, name in RULES:
        for source in sorted(root.rglob("*")):
            if not source.is_file():
                continue
            relative = source.relative_to(root)
            parts = set(relative.parts[:-1])
            # The nozzle dictionary is a required data asset, not product history.
            nozzle_dictionary = name == "nozzle_agent" and str(relative).replace("\\", "/") == "data/pipe_ref.json"
            if (parts.intersection(EXCLUDED) or any(part.startswith(".") for part in parts)) and not nozzle_dictionary:
                continue
            if name == "tube_agent" and relative.parts[0] not in ALLOWED_TUBE:
                continue
            if source.suffix.lower() not in {".py", ".json", ".dll"}:
                continue
            if source.name in {"local_config.py", "config.local.json"} or "secret" in source.name.lower():
                continue
            if name == "nozzle_agent" and relative.as_posix() == "config.json":
                continue  # Optional local provider credentials are never bundled.
            target = vendor / name / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            if source.suffix == ".py" and name == "elements_agent":
                text = source.read_text(encoding="utf-8-sig").replace("modules.element_define_agent", "elements_agent")
                target.write_text(text, encoding="utf-8")
            else:
                shutil.copyfile(str(source), str(target))
            copied.append(dict(source=str(source.relative_to(AI.parent)), target=str(target.relative_to(BASE)),
                source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                copied_sha256=hashlib.sha256(target.read_bytes()).hexdigest(), bytes=target.stat().st_size))
    atomic_json(BASE / "vendor-manifest.json", dict(schema="donglanpec.agent-backend-copies/1", files=copied))
    print(json.dumps(dict(status="copied", files=len(copied), bytes=sum(f["bytes"] for f in copied))))


if __name__ == "__main__":
    main()
