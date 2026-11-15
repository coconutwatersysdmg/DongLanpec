"""Keep observed product identity reviewable when its form is unregistered."""


def source_identity_validator(validate, products):
    observed = {(p.get("产品类型"), p.get("产品型式")) for p in products}

    def review(data, *args, **kwargs):
        errors, warnings = validate(data, *args, **kwargs)
        if (data.get("产品类型"), data.get("产品型式")) not in observed:
            return errors, warnings
        remaining, notices = [], list(warnings)
        for error in errors:
            if error.get("field") == "产品型式" and "不属于产品类型" in error.get("reason", ""):
                notices.append(dict(field="产品型式", value=data.get("产品型式"),
                    reason="保留本次输入识别的型式；独立库尚未登记，后续模板/几何适配仍需核对。"))
            else:
                remaining.append(error)
        return remaining, notices

    return review
