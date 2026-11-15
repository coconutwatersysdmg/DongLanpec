"""Render the unified application and module editors against a private test run."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

BASE = Path(__file__).resolve().parent


def verify(summary_path):
    from verify_original_ui import fixture
    from platform_core.evidence_data import EvidenceData
    summary = fixture(summary_path)
    service = EvidenceData(BASE / "workspace")
    home = BASE / "workspace" / "evidence" / "unified-ui"
    home.mkdir(parents=True, exist_ok=True)
    receipt = dict(test_run=summary["run_id"], pages=[], modules=[], interactions=[], formal_product_changes=False)
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", PYTHONIOENCODING="utf-8")
    summary_file = Path(summary_path).resolve()
    for page in ("chat", "modules", "space", "execution", "review"):
        image = home / (page + ".png")
        with (home / (page + ".log")).open("wb") as output:
            result = subprocess.run([sys.executable, "-X", "faulthandler", str(BASE / "run.py"), "--result", str(summary_file), "--page", page, "--screenshot", str(image)], env=env, stdout=output, stderr=subprocess.STDOUT, timeout=45)
        if result.returncode: raise RuntimeError(str(home / (page + ".log")))
        receipt["pages"].append(dict(page=page, screenshot=str(image), ok=True))
    for module in ("project", "conditions", "elements", "nozzles", "tube_bundle"):
        context = service.prepare(summary["run_id"], summary["products"][0]["id"], module)
        image = home / ("module-" + module + ".png")
        with (home / ("module-" + module + ".log")).open("wb") as output:
            result = subprocess.run([sys.executable, "-X", "faulthandler", str(BASE / "module_runtime.py"), str(context), "--snapshot", str(image)], env=env, stdout=output, stderr=subprocess.STDOUT, timeout=75)
        if result.returncode: raise RuntimeError(str(home / ("module-" + module + ".log")))
        value = json.loads((context.parent / "unified-snapshot.json").read_text(encoding="utf-8"))
        receipt["modules"].append(dict(value, screenshot=str(image), context=str(context)))
        with (home / ("interaction-" + module + ".log")).open("wb") as output:
            result = subprocess.run([sys.executable, "-X", "faulthandler", str(BASE / "module_runtime.py"), str(context), "--probe"], env=env, stdout=output, stderr=subprocess.STDOUT, timeout=90)
        if result.returncode: raise RuntimeError(str(home / ("interaction-" + module + ".log")))
        interaction = json.loads((context.parent / "unified-interaction.json").read_text(encoding="utf-8"))
        from platform_core.orchestrator import Orchestrator
        summary = Orchestrator(BASE / "workspace").import_evidence(context.parent / "update.json")
        if module in ("conditions", "nozzles"):
            with service.connection() as conn:
                with conn.cursor() as cursor:
                    if module == "conditions":
                        cursor.execute("SELECT 壳程数值 AS value FROM 产品设计活动库.产品设计活动表_设计数据表 WHERE 产品ID=%s AND 参数名称='设计压力*'", (summary["products"][0]["id"],))
                        expected = 2.1
                    else:
                        cursor.execute("SELECT 外伸高度 AS value FROM 产品设计活动库.产品设计活动表_管口表 WHERE 产品ID=%s AND 管口ID=1", (summary["products"][0]["id"],))
                        expected = 190.0
                    actual = float(cursor.fetchone()["value"])
                    assert actual == expected
                    interaction["private_database_readback"] = actual
        interaction["reviewed_product_version"] = summary["products"][0]["draft_data_sha256"]
        receipt["interactions"].append(interaction)
    from platform_core.private_database import atomic_json
    atomic_json(home / "verification.json", receipt)
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("summary")
    print(json.dumps(verify(parser.parse_args().summary), ensure_ascii=False))
