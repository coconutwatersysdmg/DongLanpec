"""Target existing source codes (1, L1, etc.) without renaming original nozzles."""
import re


def bind_source_codes(agent):
    original = agent.parser.parse

    def parse(text):
        intent = original(text)
        if intent.action not in ("update", "delete") or intent.target_code:
            return intent
        codes = sorted({str(r.get("管口代号", "")) for r in agent.rows if r.get("管口代号")}, key=len, reverse=True)
        for code in codes:
            prefix = r"(?:把|将|修改|更新|删除|删掉|移除|去掉)\s*(?:管口\s*)?"
            if re.search(prefix + re.escape(code) + r"(?=\s|的|$)", text, re.I):
                intent.target_code = code
                break
        return intent

    agent.parser.parse = parse
    return agent
