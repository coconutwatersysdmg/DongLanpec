import pymysql
import pandas as pd
from collections import defaultdict

# ===============================
# 配置区（请确认）
# ===============================
DB_HOST = "localhost"
DB_USER = "root"
DB_PASS = "123456"
DB_NAME = "元件库"
TABLE_NAME = "布管参数默认表"

# 如果为 False 则只做预览并打印前几组的旧/新顺序（更安全）
# 如果确认无误再改成 True 执行写库
WRITE_TO_DB = True

# 需要放到最前的固定顺序（若存在则按此顺序排列）
HEAD_ORDER = [
    "是否以外径为基准",
"管程程数",
"管程分程形式",
"壳程程数",
"公称直径 DN",
"壳体内直径 Di",
"布管限定圆 DL",
"换热管布置方式",
"换热管外径 do",
"换热管壁厚 δ",
"换热管排列方式",
"换热管公称长度 LN",
"换热管中心距 S",
"折流板外径",
"折流/支持板间距",

"折流板切口方向",
"折流板要求切口率 (%)",
"折流板切口与中心线间距",
]

# 打印预览的组数上限
PREVIEW_GROUPS = 10

# ===============================
# 1. 连接数据库并读取表
# ===============================
conn = pymysql.connect(
    host=DB_HOST,
    user=DB_USER,
    password=DB_PASS,
    database=DB_NAME,
    charset="utf8mb4"
)

df = pd.read_sql(f"SELECT * FROM {TABLE_NAME}", conn)

# 保证用于原始顺序的 ID 是数值（无法转换的放到很后面）
df["元件附加参数ID_num"] = pd.to_numeric(df.get("布管参数ID"), errors="coerce")
df["元件附加参数ID_num"] = df["布管参数ID_num"].fillna(10**9).astype(int)

# 先按元件ID, 模板ID, 原始ID 排序，确保“原始顺序”被正确捕获
df_sorted = df.sort_values(by=["参数名"], kind="stable").copy()

# ===============================
# 2. 对每组进行重排（将 HEAD_ORDER 中存在的参数按指定顺序移到前面）
# ===============================
output_records = []
groups = df_sorted.groupby(["参数名"], sort=False)

for (comp_id, tmpl_id), group in groups:
    records = group.to_dict("records")  # 按原始顺序
    # 将 HEAD_ORDER 中的项收集（并保持同名项出现的原始相对顺序）
    name_to_recs = defaultdict(list)
    others = []
    for rec in records:
        pname = str(rec.get("参数名称", "")).strip()
        if pname in HEAD_ORDER:
            name_to_recs[pname].append(rec)
        else:
            others.append(rec)

    # 生成新的组顺序：依次把 HEAD_ORDER 中存在的项加入（保持每个 name 内部的原始顺序），然后接回其它项（others）保持原始顺序
    new_group = []
    for name in HEAD_ORDER:
        if name in name_to_recs:
            new_group.extend(name_to_recs[name])
    new_group.extend(others)

    # 如果 HEAD_ORDER 中都不存在，则 new_group 就是原始 others（不改变）
    output_records.extend(new_group)

# 变回 DataFrame 并生成新的 ID（顺序连续）
new_df = pd.DataFrame(output_records).reset_index(drop=True)
new_df["新元件附加参数ID"] = range(1, len(new_df) + 1)

# ===============================
# 3. 预览：打印前若干组的 old vs new 顺序供核对
# ===============================
def get_group_key(row):
    return (row["元件ID"], row["模板ID"])

# 建 map: (元件ID,模板ID) -> list of 参数名称 （原始）
orig_map = {}
for (comp_id, tmpl_id), group in df_sorted.groupby(["元件ID", "模板ID"], sort=False):
    orig_map[(comp_id, tmpl_id)] = [str(r.get("参数名称", "")).strip() for _, r in group.iterrows()]

new_map = {}
for (comp_id, tmpl_id), group in new_df.groupby(["元件ID", "模板ID"], sort=False):
    new_map[(comp_id, tmpl_id)] = [str(r.get("参数名称", "")).strip() for _, r in group.iterrows()]

print("------ 预览（每组显示旧顺序 -> 新顺序，最多展示前 {} 组） ------".format(PREVIEW_GROUPS))
count = 0
for key in orig_map:
    old_seq = orig_map[key]
    new_seq = new_map.get(key, [])
    # 仅在序列不同或包含 HEAD_ORDER 中项时打印，便于关注变动
    if old_seq != new_seq:
        print(f"\n元件ID={key[0]} 模板ID={key[1]}")
        print("旧顺序: ", old_seq)
        print("新顺序: ", new_seq)
        count += 1
    else:
        # 若没变且还没打印过足够样本，我们可选择略过以减量输出
        if count < PREVIEW_GROUPS and len(old_seq) > 0:
            print(f"\n元件ID={key[0]} 模板ID={key[1]} (未变)")
            print("顺序: ", old_seq)
            count += 1
    if count >= PREVIEW_GROUPS:
        break

# ===============================
# 4. 写库（两步法）或仅预览
# ===============================
if WRITE_TO_DB:
    with conn.cursor() as cursor:
        # Step1: 写入临时负数 ID（使用旧定位：元件附加参数ID + 元件ID + 模板ID）
        for _, row in new_df.iterrows():
            old_id = row["元件附加参数ID"]
            new_id = int(row["新元件附加参数ID"])
            comp_id = row["元件ID"]
            tmpl_id = row["模板ID"]

            update_sql = f"""
                UPDATE {TABLE_NAME}
                SET 元件附加参数ID = %s
                WHERE 元件附加参数ID = %s AND 元件ID = %s AND 模板ID = %s
            """
            cursor.execute(update_sql, (-new_id, int(old_id), comp_id, tmpl_id))

        # Step2: 把负数转回正数
        cursor.execute(f"""
            UPDATE {TABLE_NAME}
            SET 元件附加参数ID = -元件附加参数ID
            WHERE 元件附加参数ID < 0
        """)
    conn.commit()
    conn.close()
    print("\n✅ 已将新顺序写回数据库（两步法避免主键冲突）。")
else:
    conn.close()
    print("\n⚠️ 当前为预览模式（WRITE_TO_DB=False），未向数据库写入任何更改。")
    print("如确认无误，将 WRITE_TO_DB = True 并重新运行脚本以写回数据库。")
