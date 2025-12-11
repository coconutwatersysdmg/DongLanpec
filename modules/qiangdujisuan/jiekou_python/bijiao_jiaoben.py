import json
import os

def normalize_key(key: str) -> str:
    """
    统一 key 名称，把 '浮头管束' 和 '管束' 当成一个
    """
    if "浮头管束" in key:
        return key.replace("浮头管束", "管束")
    return key

def collect_keys(obj, prefix=""):
    """
    递归收集 JSON 的所有 key 路径，并进行 key 归一化
    """
    keys = set()
    if isinstance(obj, dict):
        for k, v in obj.items():
            k_norm = normalize_key(k)
            new_path = f"{prefix}.{k_norm}" if prefix else k_norm
            keys.add(new_path)
            keys |= collect_keys(v, new_path)
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            new_path = f"{prefix}[{i}]"
            keys |= collect_keys(item, new_path)
    return keys

def main(fileA="BESInput.json", fileB="shuru_jisuan.json", output="diff_keys.txt"):
    with open(fileA, "r", encoding="utf-8") as f:
        dataA = json.load(f)
    with open(fileB, "r", encoding="utf-8") as f:
        dataB = json.load(f)

    keysA = collect_keys(dataA)
    keysB = collect_keys(dataB)

    missing_in_A = sorted(keysB - keysA)  # A 缺少的 key
    missing_in_B = sorted(keysA - keysB)  # B 缺少的 key

    with open(output, "w", encoding="utf-8") as f:
        if not missing_in_A and not missing_in_B:
            f.write("两个 JSON 的 key 完全一致。\n")
        else:
            f.write(f"{os.path.basename(fileA)} 缺少的 key（在 {os.path.basename(fileB)} 中存在）：\n\n")
            if missing_in_A:
                for key in missing_in_A:
                    f.write(f"{key}\n")
            else:
                f.write("（无）\n")

            f.write("\n")
            f.write(f"{os.path.basename(fileB)} 缺少的 key（在 {os.path.basename(fileA)} 中存在）：\n\n")
            if missing_in_B:
                for key in missing_in_B:
                    f.write(f"{key}\n")
            else:
                f.write("（无）\n")

    print(f"对比完成，结果已写入 {os.path.abspath(output)}")

if __name__ == "__main__":
    main()
