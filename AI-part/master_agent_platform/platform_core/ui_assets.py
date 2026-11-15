"""Build private copies of the original AI interfaces and their required assets."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil

from .private_database import atomic_json

BASE = Path(__file__).resolve().parent.parent
SOURCE = BASE.parent
PACKAGES = {"project": ("ai_xiangmuguanli", "project_agent"),
            "conditions": ("ai_tiaojianshuru", "condition_agent"),
            "elements": ("ai_yuanjiandingyi", "elements_agent"),
            "nozzles": ("ai_guankoudingyi", "nozzle_agent"),
            "tube_bundle": ("ai_buguan", "tube_agent")}
EXCLUDED = {"tests", "tools", "docs", "output", "outputs", "artifacts", "legacy", "legacy_demo",
            "_vendor", "__pycache__", "modules", "venv", "build", "dist", "backup"}
ASSET_SUFFIXES = {".py", ".png", ".jpg", ".jpeg", ".svg", ".ui", ".qss", ".qrc", ".dll", ".ttf", ".ttc"}


def ensure_ui_assets():
    destination = BASE / "ui_vendor"
    manifest_path = BASE / "ui-vendor-manifest.json"
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if all((BASE / f["target"]).is_file() for f in manifest["files"]):
            return destination
        raise RuntimeError("原界面副本不完整，请核对 ui-vendor-manifest.json；未回退原业务路径。")
    if destination.exists():
        raise RuntimeError("原界面复制目录已存在但没有完成回执，保留现场，拒绝覆盖。")
    entries = []
    def copy(source, target, transform=False):
        target.parent.mkdir(parents=True, exist_ok=True)
        if transform:
            content = source.read_text(encoding="utf-8-sig").replace("modules.element_define_agent", "elements_agent")
            target.write_text(content, encoding="utf-8")
        else:
            shutil.copyfile(source, target)
        entries.append(dict(source=str(source.relative_to(SOURCE.parent)), target=str(target.relative_to(BASE)),
            source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(), sha256=hashlib.sha256(target.read_bytes()).hexdigest(),
            bytes=target.stat().st_size))
    for original, package in PACKAGES.values():
        root = SOURCE / original
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(root)
            parents = rel.parts[:-1]
            if any(part in EXCLUDED or part.startswith(".") for part in parents):
                continue
            if path.name in ("local_config.py",) or "secret" in path.name.lower():
                continue
            dictionary = str(rel).replace("\\", "/") in ("param_dict.json", "data/pipe_ref.json")
            if path.suffix.lower() not in ASSET_SUFFIXES and not dictionary:
                continue
            copy(path, destination / package / rel, transform=package == "elements_agent" and path.suffix == ".py")
    # Retain only the actual backend dependencies used by the AI interfaces.
    business = SOURCE.parent / "modules"
    for name in ("cailiaodingyi/db_cnt.py", "cailiaodingyi/funcs/funcs_pdf_change.py", "cailiaodingyi/funcs/funcs_pdf_input.py"):
        copy(business / name, destination / "modules" / name)
    for path in (SOURCE / "ai_buguan" / "modules" / "buguan" / "buguan_ziyong" / "tube_pass").glob("*.py"):
        copy(path, destination / "modules" / "buguan" / "buguan_ziyong" / "tube_pass" / path.name)
    for name in ("__init__.py",):
        for folder in ("modules", "modules/cailiaodingyi", "modules/cailiaodingyi/funcs", "modules/chanpinguanli",
                       "modules/buguan", "modules/buguan/buguan_ziyong"):
            target = destination / folder / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("", encoding="utf-8")
    # The original product picker needs only these two connections. Do not copy
    # the main program or its global product-manager state.
    helper = destination / "modules" / "chanpinguanli" / "common_usage.py"
    helper.write_text('import pymysql\n\ndef get_mysql_connection_product():\n    return pymysql.connect(database="产品需求库", cursorclass=pymysql.cursors.DictCursor)\n\ndef get_mysql_connection_project():\n    return pymysql.connect(database="项目需求库", cursorclass=pymysql.cursors.DictCursor)\n', encoding="utf-8")
    # Keep the original optional table/schematic view available to the nozzle UI.
    ui_root = business / "guankoudingyi"
    for folder in ("ui", "resource"):
        for path in (ui_root / folder).rglob("*"):
            if path.is_file() and path.suffix.lower() in ASSET_SUFFIXES:
                copy(path, destination / "nozzle_resources" / folder / path.relative_to(ui_root / folder))
    atomic_json(manifest_path, dict(schema="donglanpec.original-agent-ui-copies/1", files=entries,
        generated_adapters=[str(helper.relative_to(BASE))], excludes="credentials, histories, virtual environments and main program"))
    return destination
