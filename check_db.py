import os
import json
import csv
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

try:
    from pythonnet import load
    try:
        load("coreclr")
    except Exception:
        pass
except Exception:
    pass

try:
    import clr
except Exception as e:
    raise RuntimeError(
        "未安装 pythonnet，请先执行：pip install pythonnet\n"
        f"原始错误：{e}"
    )


class LiteDBBridge:
    def __init__(self):
        self.db = None
        self.LiteDatabase = None
        self.JsonSerializer = None
        self.BsonMapper = None
        self.BsonValue = None
        self.ObjectId = None
        self._dll_loaded = False

    def _get_collection(self, collection_name: str):
        if self.db is None:
            raise RuntimeError("数据库未打开")
        return self.db.GetCollection[self.BsonDocument](collection_name)
    def load_dll(self, dll_path: str):
        import os
        from System.Reflection import Assembly

        dll_path = os.path.abspath(dll_path)

        if not os.path.isfile(dll_path):
            raise FileNotFoundError(f"LiteDB.dll 不存在：{dll_path}")

        Assembly.LoadFrom(dll_path)

        from LiteDB import (
            LiteDatabase, JsonSerializer, BsonMapper,
            BsonValue, ObjectId, BsonDocument, BsonArray
        )

        self.LiteDatabase = LiteDatabase
        self.JsonSerializer = JsonSerializer
        self.BsonMapper = BsonMapper
        self.BsonValue = BsonValue
        self.ObjectId = ObjectId
        self.BsonDocument = BsonDocument
        self._dll_loaded = True
        self.BsonArray = BsonArray
    def open_db(self, db_path: str, password: str = ""):
        if not self._dll_loaded:
            raise RuntimeError("请先加载 LiteDB.dll")

        self.close()

        if password:
            conn_str = f"Filename={db_path};Password={password}"
        else:
            conn_str = f"Filename={db_path}"

        self.db = self.LiteDatabase(conn_str)

    def close(self):
        if self.db is not None:
            try:
                self.db.Dispose()
            except Exception:
                pass
            self.db = None

    def get_collection_names(self):
        if self.db is None:
            return []
        return sorted([str(x) for x in self.db.GetCollectionNames()])

    def ensure_collection(self, name: str):
        if self.db is None:
            raise RuntimeError("数据库未打开")
        self._get_collection(name)
    def drop_collection(self, name: str):
        if self.db is None:
            raise RuntimeError("数据库未打开")
        return bool(self.db.DropCollection(name))

    def _doc_to_json_text(self, doc):
        try:
            return str(self.JsonSerializer.Serialize(doc))
        except Exception:
            return str(doc)

    def _json_text_to_bson_document(self, text: str):
        data = json.loads(text)
        if not isinstance(data, dict):
            raise ValueError("文档必须是 JSON 对象")
        return self._py_dict_to_bson_document(data)

    def _py_dict_to_bson_document(self, data: dict):
        doc = self.BsonDocument()
        for k, v in data.items():
            doc[k] = self._py_to_bson_value(v)
        return doc

    def _py_list_to_bson_array(self, data: list):
        arr = self.BsonArray()
        for item in data:
            arr.Add(self._py_to_bson_value(item))
        return arr

    def _py_to_bson_value(self, value):
        if value is None:
            return self.BsonValue.Null

        if isinstance(value, bool):
            return self.BsonValue(value)

        if isinstance(value, int):
            return self.BsonValue(value)

        if isinstance(value, float):
            return self.BsonValue(value)

        if isinstance(value, str):
            # 如果是 24 位十六进制字符串，可按 ObjectId 处理
            if len(value) == 24:
                try:
                    oid = self.ObjectId.Parse(value)
                    return self.BsonValue(oid)
                except Exception:
                    pass
            return self.BsonValue(value)

        if isinstance(value, dict):
            return self.BsonValue(self._py_dict_to_bson_document(value))

        if isinstance(value, list):
            return self.BsonValue(self._py_list_to_bson_array(value))

        # 兜底：转字符串
        return self.BsonValue(str(value))
    def list_documents(self, collection_name: str, limit: int = 300):
        if self.db is None:
            raise RuntimeError("数据库未打开")

        col = self.db.GetCollection[self.BsonDocument](collection_name)
        docs = []
        count = 0

        for doc in col.FindAll():
            txt = self._doc_to_json_text(doc)
            try:
                py = json.loads(txt)
            except Exception:
                py = {"_raw": txt}
            docs.append(py)
            count += 1
            if count >= limit:
                break
        return docs

    def insert_document(self, collection_name: str, json_text: str):
        col = self.db.GetCollection[self.BsonDocument](collection_name)
        doc = self._json_text_to_bson_document(json_text)
        result = col.Insert(doc)
        return str(result)

    def update_document(self, collection_name: str, json_text: str):
        col = self.db.GetCollection[self.BsonDocument](collection_name)
        doc = self._json_text_to_bson_document(json_text)
        return bool(col.Update(doc))

    def upsert_document(self, collection_name: str, json_text: str):
        col = self.db.GetCollection[self.BsonDocument](collection_name)
        doc = self._json_text_to_bson_document(json_text)
        return bool(col.Upsert(doc))

    def _build_id_candidates(self, text: str):
        candidates = []
        t = text.strip()

        # 1. 先试字符串
        try:
            candidates.append(self.BsonValue(t))
        except Exception:
            pass

        # 2. 再试 int
        try:
            if t.isdigit() or (t.startswith("-") and t[1:].isdigit()):
                candidates.append(self.BsonValue(int(t)))
        except Exception:
            pass

        # 3. 再试 float
        try:
            if "." in t:
                candidates.append(self.BsonValue(float(t)))
        except Exception:
            pass

        # 4. 再试 ObjectId
        try:
            if len(t) == 24:
                candidates.append(self.BsonValue(self.ObjectId.Parse(t)))
        except Exception:
            pass

        # 5. bool
        try:
            if t.lower() == "true":
                candidates.append(self.BsonValue(True))
            elif t.lower() == "false":
                candidates.append(self.BsonValue(False))
        except Exception:
            pass

        return candidates
    def delete_by_id(self, collection_name: str, id_text: str):
        if self.db is None:
            raise RuntimeError("数据库未打开")
        if not id_text.strip():
            raise ValueError("删除时需要提供 _id")

        col = self._get_collection(collection_name)
        candidates = self._build_id_candidates(id_text.strip())

        for bson_id in candidates:
            try:
                if col.Delete(bson_id):
                    return True
            except Exception:
                pass

        return False

    def find_by_id(self, collection_name: str, id_text: str):
        if self.db is None:
            raise RuntimeError("数据库未打开")
        if not id_text.strip():
            raise ValueError("查询时需要提供 _id")

        col = self._get_collection(collection_name)
        candidates = self._build_id_candidates(id_text.strip())

        for bson_id in candidates:
            try:
                doc = col.FindById(bson_id)
                if doc is not None:
                    return self._doc_to_json_text(doc)
            except Exception:
                pass

        return None
    def _parse_id_value(self, text: str):
        t = text.strip()

        if len(t) == 24:
            try:
                return self.ObjectId.Parse(t)
            except Exception:
                pass

        if t.lower() == "true":
            return self.BsonValue(True)
        if t.lower() == "false":
            return self.BsonValue(False)

        try:
            if t.isdigit() or (t.startswith("-") and t[1:].isdigit()):
                return self.BsonValue(int(t))
        except Exception:
            pass

        try:
            if "." in t:
                return self.BsonValue(float(t))
        except Exception:
            pass

        return self.BsonValue(t)


class LiteDBManagerApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("LiteDB 管理器（Python）")
        self.geometry("1380x820")
        self.minsize(1100, 700)

        self.bridge = LiteDBBridge()
        self.current_collection = ""
        self.current_docs = []
        self.filtered_docs = []

        self._build_ui()

    def _build_ui(self):
        top = ttk.Frame(self, padding=8)
        top.pack(fill="x")

        ttk.Button(top, text="1. 加载 LiteDB.dll", command=self.pick_dll).pack(side="left")
        ttk.Button(top, text="2. 打开 .db", command=self.pick_db).pack(side="left", padx=(8, 0))
        ttk.Button(top, text="刷新集合", command=self.load_collections).pack(side="left", padx=(8, 0))
        ttk.Button(top, text="新建集合", command=self.create_collection).pack(side="left", padx=(8, 0))
        ttk.Button(top, text="删除集合", command=self.delete_collection).pack(side="left", padx=(8, 0))

        self.status_label = ttk.Label(top, text="先加载 LiteDB.dll，再打开数据库")
        self.status_label.pack(side="left", padx=(16, 0))

        top2 = ttk.Frame(self, padding=(8, 0, 8, 8))
        top2.pack(fill="x")

        ttk.Label(top2, text="密码：").pack(side="left")
        self.password_var = tk.StringVar()
        ttk.Entry(top2, textvariable=self.password_var, width=20, show="*").pack(side="left")

        ttk.Label(top2, text="  加载上限：").pack(side="left", padx=(12, 0))
        self.limit_var = tk.StringVar(value="300")
        ttk.Entry(top2, textvariable=self.limit_var, width=8).pack(side="left")

        ttk.Label(top2, text="  文档筛选：").pack(side="left", padx=(12, 0))
        self.filter_var = tk.StringVar()
        filter_entry = ttk.Entry(top2, textvariable=self.filter_var, width=28)
        filter_entry.pack(side="left")
        filter_entry.bind("<KeyRelease>", self.apply_filter)

        ttk.Label(top2, text="  _id：").pack(side="left", padx=(12, 0))
        self.id_var = tk.StringVar()
        ttk.Entry(top2, textvariable=self.id_var, width=28).pack(side="left")
        ttk.Button(top2, text="按 _id 查询", command=self.find_one_by_id).pack(side="left", padx=(8, 0))
        ttk.Button(top2, text="按 _id 删除", command=self.delete_one_by_id).pack(side="left", padx=(8, 0))

        main = ttk.PanedWindow(self, orient="horizontal")
        main.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        left = ttk.Frame(main, padding=8)
        center = ttk.Frame(main, padding=8)
        right = ttk.Frame(main, padding=8)
        main.add(left, weight=1)
        main.add(center, weight=2)
        main.add(right, weight=3)

        ttk.Label(left, text="集合（Collections）", font=("Microsoft YaHei", 11, "bold")).pack(anchor="w")
        self.collection_list = tk.Listbox(left)
        self.collection_list.pack(fill="both", expand=True, pady=(8, 0))
        self.collection_list.bind("<<ListboxSelect>>", self.on_collection_select)

        mid_top = ttk.Frame(center)
        mid_top.pack(fill="x")
        self.docs_info = ttk.Label(mid_top, text="未选择集合")
        self.docs_info.pack(side="left")
        ttk.Button(mid_top, text="重新加载文档", command=self.reload_current_collection).pack(side="right")

        self.doc_list = tk.Listbox(center)
        self.doc_list.pack(fill="both", expand=True, pady=(8, 0))
        self.doc_list.bind("<<ListboxSelect>>", self.on_doc_select)

        right_top = ttk.Frame(right)
        right_top.pack(fill="x")
        ttk.Label(right_top, text="文档 JSON", font=("Microsoft YaHei", 11, "bold")).pack(side="left")
        ttk.Button(right_top, text="清空编辑区", command=self.clear_editor).pack(side="right")

        self.editor = tk.Text(right, wrap="none", undo=True, font=("Consolas", 10))
        self.editor.pack(fill="both", expand=True, pady=(8, 8))

        xbar = ttk.Scrollbar(right, orient="horizontal", command=self.editor.xview)
        xbar.pack(fill="x")
        self.editor.configure(xscrollcommand=xbar.set)

        btns = ttk.Frame(right)
        btns.pack(fill="x", pady=(8, 0))

        ttk.Button(btns, text="新增 Insert", command=self.insert_doc).pack(side="left")
        ttk.Button(btns, text="修改 Update", command=self.update_doc).pack(side="left", padx=(8, 0))
        ttk.Button(btns, text="保存或新增 Upsert", command=self.upsert_doc).pack(side="left", padx=(8, 0))
        ttk.Button(btns, text="格式化 JSON", command=self.format_json).pack(side="left", padx=(8, 0))
        ttk.Button(btns, text="导出当前集合 JSON", command=self.export_json).pack(side="right")
        ttk.Button(btns, text="导出当前集合 CSV", command=self.export_csv).pack(side="right", padx=(0, 8))

    def pick_dll(self):
        path = filedialog.askopenfilename(
            title="选择 LiteDB.dll",
            filetypes=[("DLL 文件", "*.dll"), ("所有文件", "*.*")]
        )
        if not path:
            return
        try:
            self.bridge.load_dll(path)
            self.status_label.config(text=f"已加载 DLL：{path}")
        except Exception as e:
            messagebox.showerror("加载失败", f"加载 LiteDB.dll 失败：\n{e}")

    def pick_db(self):
        path = filedialog.askopenfilename(
            title="选择 LiteDB 数据库文件",
            filetypes=[("数据库文件", "*.db *.ldb"), ("所有文件", "*.*")]
        )
        if not path:
            return
        try:
            self.bridge.open_db(path, self.password_var.get().strip())
            self.status_label.config(text=f"已打开数据库：{path}")
            self.load_collections()
        except Exception as e:
            messagebox.showerror("打开失败", f"打开数据库失败：\n{e}")

    def load_collections(self):
        try:
            names = self.bridge.get_collection_names()
            self.collection_list.delete(0, tk.END)
            for name in names:
                self.collection_list.insert(tk.END, name)
            self.docs_info.config(text=f"共 {len(names)} 个集合")
        except Exception as e:
            messagebox.showerror("读取失败", f"读取集合失败：\n{e}")

    def create_collection(self):
        win = tk.Toplevel(self)
        win.title("新建集合")
        win.geometry("320x120")
        win.transient(self)
        win.grab_set()

        ttk.Label(win, text="集合名：").pack(pady=(15, 4))
        name_var = tk.StringVar()
        ttk.Entry(win, textvariable=name_var, width=32).pack()

        def do_create():
            name = name_var.get().strip()
            if not name:
                messagebox.showwarning("提示", "请输入集合名", parent=win)
                return
            try:
                self.bridge.ensure_collection(name)
                self.load_collections()
                win.destroy()
                messagebox.showinfo("成功", f"集合已可用：{name}")
            except Exception as e:
                messagebox.showerror("失败", f"创建集合失败：\n{e}", parent=win)

        ttk.Button(win, text="确定", command=do_create).pack(pady=12)

    def delete_collection(self):
        if not self.current_collection:
            messagebox.showwarning("提示", "请先选择集合")
            return
        if not messagebox.askyesno("确认", f"确定删除集合 {self.current_collection} 吗？"):
            return
        try:
            ok = self.bridge.drop_collection(self.current_collection)
            self.current_collection = ""
            self.current_docs = []
            self.filtered_docs = []
            self.collection_list.selection_clear(0, tk.END)
            self.doc_list.delete(0, tk.END)
            self.editor.delete("1.0", tk.END)
            self.load_collections()
            messagebox.showinfo("结果", "删除成功" if ok else "删除失败或集合不存在")
        except Exception as e:
            messagebox.showerror("失败", f"删除集合失败：\n{e}")

    def on_collection_select(self, event=None):
        sel = self.collection_list.curselection()
        if not sel:
            return
        self.show_collection(self.collection_list.get(sel[0]))

    def reload_current_collection(self):
        if self.current_collection:
            self.show_collection(self.current_collection)

    def show_collection(self, name: str):
        try:
            limit = int(self.limit_var.get().strip() or "300")
        except Exception:
            limit = 300

        try:
            docs = self.bridge.list_documents(name, limit=limit)
            self.current_collection = name
            self.current_docs = docs
            self.filtered_docs = docs[:]
            self.render_doc_list(docs)
            self.docs_info.config(text=f"当前集合：{name}    已加载 {len(docs)} 条")
            self.editor.delete("1.0", tk.END)
        except Exception as e:
            messagebox.showerror("读取失败", f"读取文档失败：\n{e}")

    def render_doc_list(self, docs):
        self.doc_list.delete(0, tk.END)
        for i, doc in enumerate(docs, start=1):
            _id = doc.get("_id", "") if isinstance(doc, dict) else ""
            preview = json.dumps(doc, ensure_ascii=False)
            if len(preview) > 120:
                preview = preview[:120] + " ..."
            self.doc_list.insert(tk.END, f"{i}. _id={_id} | {preview}")

    def on_doc_select(self, event=None):
        sel = self.doc_list.curselection()
        if not sel:
            return
        idx = sel[0]
        if idx >= len(self.filtered_docs):
            return
        doc = self.filtered_docs[idx]
        self.editor.delete("1.0", tk.END)
        self.editor.insert("1.0", json.dumps(doc, ensure_ascii=False, indent=2))
        if isinstance(doc, dict) and "_id" in doc:
            self.id_var.set(str(doc["_id"]))

    def apply_filter(self, event=None):
        kw = self.filter_var.get().strip().lower()
        if not kw:
            self.filtered_docs = self.current_docs[:]
            self.render_doc_list(self.filtered_docs)
            return

        out = []
        for d in self.current_docs:
            s = json.dumps(d, ensure_ascii=False).lower()
            if kw in s:
                out.append(d)
        self.filtered_docs = out
        self.render_doc_list(out)

    def get_editor_text(self):
        return self.editor.get("1.0", tk.END).strip()

    def clear_editor(self):
        self.editor.delete("1.0", tk.END)

    def format_json(self):
        text = self.get_editor_text()
        if not text:
            return
        try:
            obj = json.loads(text)
            self.editor.delete("1.0", tk.END)
            self.editor.insert("1.0", json.dumps(obj, ensure_ascii=False, indent=2))
        except Exception as e:
            messagebox.showerror("格式错误", f"不是合法 JSON：\n{e}")

    def insert_doc(self):
        if not self.current_collection:
            messagebox.showwarning("提示", "请先选择集合")
            return
        text = self.get_editor_text()
        if not text:
            return
        try:
            result_id = self.bridge.insert_document(self.current_collection, text)
            self.reload_current_collection()
            messagebox.showinfo("成功", f"新增成功，_id：{result_id}")
        except Exception as e:
            messagebox.showerror("新增失败", f"{e}")

    def update_doc(self):
        if not self.current_collection:
            messagebox.showwarning("提示", "请先选择集合")
            return
        text = self.get_editor_text()
        if not text:
            return
        try:
            ok = self.bridge.update_document(self.current_collection, text)
            self.reload_current_collection()
            messagebox.showinfo("结果", "Update 成功" if ok else "未更新到文档，请检查 _id")
        except Exception as e:
            messagebox.showerror("修改失败", f"{e}")

    def upsert_doc(self):
        if not self.current_collection:
            messagebox.showwarning("提示", "请先选择集合")
            return
        text = self.get_editor_text()
        if not text:
            return
        try:
            ok = self.bridge.upsert_document(self.current_collection, text)
            self.reload_current_collection()
            messagebox.showinfo("结果", "Upsert 成功" if ok else "Upsert 未生效")
        except Exception as e:
            messagebox.showerror("失败", f"{e}")

    def find_one_by_id(self):
        if not self.current_collection:
            messagebox.showwarning("提示", "请先选择集合")
            return
        _id = self.id_var.get().strip()
        if not _id:
            return
        try:
            txt = self.bridge.find_by_id(self.current_collection, _id)
            if txt is None:
                messagebox.showinfo("结果", "未找到文档")
                return
            try:
                obj = json.loads(txt)
                txt = json.dumps(obj, ensure_ascii=False, indent=2)
            except Exception:
                pass
            self.editor.delete("1.0", tk.END)
            self.editor.insert("1.0", txt)
        except Exception as e:
            messagebox.showerror("查询失败", f"{e}")

    def delete_one_by_id(self):
        if not self.current_collection:
            messagebox.showwarning("提示", "请先选择集合")
            return
        _id = self.id_var.get().strip()
        if not _id:
            return
        if not messagebox.askyesno("确认", f"确定删除 _id={_id} 的文档吗？"):
            return
        try:
            ok = self.bridge.delete_by_id(self.current_collection, _id)
            self.reload_current_collection()
            messagebox.showinfo("结果", "删除成功" if ok else "未找到对应文档")
        except Exception as e:
            messagebox.showerror("删除失败", f"{e}")

    def export_json(self):
        if not self.current_collection:
            return
        path = filedialog.asksaveasfilename(
            title="导出 JSON",
            defaultextension=".json",
            filetypes=[("JSON 文件", "*.json")]
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self.filtered_docs, f, ensure_ascii=False, indent=2)
            messagebox.showinfo("成功", f"已导出：\n{path}")
        except Exception as e:
            messagebox.showerror("导出失败", f"{e}")

    def export_csv(self):
        if not self.current_collection or not self.filtered_docs:
            return
        path = filedialog.asksaveasfilename(
            title="导出 CSV",
            defaultextension=".csv",
            filetypes=[("CSV 文件", "*.csv")]
        )
        if not path:
            return
        try:
            keys = set()
            for d in self.filtered_docs:
                if isinstance(d, dict):
                    keys.update(d.keys())
            headers = list(keys)

            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.DictWriter(f, fieldnames=headers)
                writer.writeheader()
                for d in self.filtered_docs:
                    row = {}
                    for k in headers:
                        v = d.get(k, "") if isinstance(d, dict) else ""
                        if isinstance(v, (dict, list)):
                            v = json.dumps(v, ensure_ascii=False)
                        row[k] = v
                    writer.writerow(row)

            messagebox.showinfo("成功", f"已导出：\n{path}")
        except Exception as e:
            messagebox.showerror("导出失败", f"{e}")

    def destroy(self):
        try:
            self.bridge.close()
        except Exception:
            pass
        super().destroy()


if __name__ == "__main__":
    app = LiteDBManagerApp()
    app.mainloop()