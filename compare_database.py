import re

def parse_sql_file(filepath, target_dbs):
    """解析SQL文件，提取指定库的表结构和数据量、数据样本"""
    schema = {}      # { db.table: create_table_sql }
    data_count = {}  # { db.table: insert语句数量 }
    data_samples = {}  # { db.table: [前几条数据] }

    current_db = None
    current_create = []
    schema_key = None

    with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            line_stripped = line.strip()

            # USE `xxx`;
            m = re.match(r"USE\s+`(.+?)`;", line_stripped, re.I)
            if m:
                db = m.group(1)
                current_db = db if db in target_dbs else None
                continue

            if not current_db:
                continue

            # CREATE TABLE ... 多行直到 ;
            if line_stripped.upper().startswith("CREATE TABLE"):
                current_create = [line_stripped]
                table_name = re.search(r"`(.+?)`", line_stripped).group(1)
                schema_key = f"{current_db}.{table_name}"
                schema[schema_key] = ""  # 占位
                continue
            elif current_create:
                current_create.append(line_stripped)
                if line_stripped.endswith(";"):  # CREATE TABLE 结束
                    schema[schema_key] = "\n".join(current_create)
                    current_create = []
                    schema_key = None

            # INSERT INTO
            if line_stripped.upper().startswith("INSERT INTO"):
                m = re.search(r"INSERT INTO\s+`(.+?)`", line_stripped, re.I)
                if m:
                    table_name = m.group(1)
                    schema_key = f"{current_db}.{table_name}"
                    data_count[schema_key] = data_count.get(schema_key, 0) + 1
                    if len(data_samples.get(schema_key, [])) < 5:  # 只保存前5条样本
                        data_samples.setdefault(schema_key, []).append(line_stripped)

    return schema, data_count, data_samples


def compare_sql(file1, file2, target_dbs, output_file="db_compare_report.txt"):
    schema1, data1, samples1 = parse_sql_file(file1, target_dbs)
    schema2, data2, samples2 = parse_sql_file(file2, target_dbs)

    keys1 = set(schema1.keys())
    keys2 = set(schema2.keys())

    only_in_1 = keys1 - keys2
    only_in_2 = keys2 - keys1
    common = keys1 & keys2

    with open(output_file, "w", encoding="utf-8") as f:
        f.write("数据库对比报告（仅限 材料库 / 元件库）\n\n")

        # 1. 表存在差异
        if only_in_1:
            f.write("仅在第一个文件中的表:\n")
            for k in sorted(only_in_1):
                f.write(f"  - {k}\n")
                f.write(f"    CREATE TABLE 语句:\n{schema1[k]}\n\n")
        else:
            f.write("第一个文件没有独有的表。\n\n")

        if only_in_2:
            f.write("仅在第二个文件中的表:\n")
            for k in sorted(only_in_2):
                f.write(f"  - {k}\n")
                f.write(f"    CREATE TABLE 语句:\n{schema2[k]}\n\n")
        else:
            f.write("第二个文件没有独有的表。\n\n")

        # 2. 表结构差异
        diff_schema = []
        for k in sorted(common):
            if schema1[k] != schema2[k]:
                diff_schema.append(k)
                f.write(f"表结构不同: {k}\n")
                f.write("  文件1结构:\n")
                f.write(schema1[k] + "\n")
                f.write("  文件2结构:\n")
                f.write(schema2[k] + "\n\n")
        if not diff_schema:
            f.write("两个文件的公共表结构完全一致。\n\n")

        # 3. 数据量差异
        diff_data = []
        for k in sorted(common):
            if data1.get(k, 0) != data2.get(k, 0):
                diff_data.append(k)
                f.write(f"数据量不同: {k}\n")
                f.write(f"  文件1: {data1.get(k,0)} 行\n")
                if k in samples1:
                    f.write("  文件1示例数据:\n")
                    for s in samples1[k]:
                        f.write(f"    {s}\n")
                f.write(f"  文件2: {data2.get(k,0)} 行\n")
                if k in samples2:
                    f.write("  文件2示例数据:\n")
                    for s in samples2[k]:
                        f.write(f"    {s}\n")
                f.write("\n")
        if not diff_data:
            f.write("公共表的数据量完全一致。\n")

    print(f"报告已生成: {output_file}")



if __name__ == "__main__":
    # 两个 SQL 文件路径
    file1 = "mysql_backup/all_databases_20250912_200044.sql"
    file2 = "mysql_backup/all_databases_20250912_200437.sql"

    target_dbs = {"材料库", "元件库"}

    compare_sql(file1, file2, target_dbs, "db_compare_report.txt")
