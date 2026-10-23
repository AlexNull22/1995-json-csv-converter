"""选择JSON并调用同一转换核心的本机桌面入口。"""
import argparse
import csv
import importlib.util
import os
from pathlib import Path
import queue
import sys
import threading
import time
import tkinter as tk
from tkinter import filedialog, ttk

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("converter1995", HERE / "1995_转换核心.py")
core = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = core
spec.loader.exec_module(core)
csv.field_size_limit(core.MAX_INPUT_BYTES)


class Desktop:
    def __init__(self, root, source=None, output=None):
        root.title("1995 结构化数据转换工具")
        root.geometry("1080x660")
        self.root, self.events = root, queue.Queue()
        self.result, self.error, self.running = None, None, False
        self.source = tk.StringVar(value=str(source or ""))
        self.output = tk.StringVar(value=str(output or Path.home() / "1995_转换输出"))
        self.records_key = tk.StringVar()
        self.status = tk.StringVar(value="选择JSON文件和一个尚不存在的输出目录。")
        box = ttk.Frame(root, padding=24)
        box.pack(fill="both", expand=True)
        ttk.Label(box, text="把结构化数据，变成清楚的列。", font=("Microsoft YaHei", 20)).pack(anchor="w")
        ttk.Label(box, text="1995 独立演示 · Python标准库 · 原文件保持不变").pack(anchor="w", pady=(4,16))
        for label, variable, command in [("JSON文件", self.source, self.choose_input), ("新输出目录", self.output, self.choose_output)]:
            line = ttk.Frame(box)
            line.pack(fill="x", pady=7)
            ttk.Label(line, text=label, width=12).pack(side="left")
            ttk.Entry(line, textvariable=variable).pack(side="left", fill="x", expand=True)
            ttk.Button(line, text="选择", command=command).pack(side="left", padx=10)
        line = ttk.Frame(box)
        line.pack(fill="x", pady=7)
        ttk.Label(line, text="列表字段(可选)", width=12).pack(side="left")
        ttk.Entry(line, textvariable=self.records_key, width=25).pack(side="left")
        ttk.Label(line, text="仅用于对象内的顶层记录数组；空白时直接读取整个对象或数组。").pack(side="left", padx=12)
        buttons = ttk.Frame(box)
        buttons.pack(fill="x", pady=14)
        self.convert_button = ttk.Button(buttons, text="转换并保存CSV", command=self.start)
        self.convert_button.pack(side="left")
        self.open_button = ttk.Button(buttons, text="打开结果目录", command=self.open_output, state="disabled")
        self.open_button.pack(side="left", padx=12)
        ttk.Label(box, textvariable=self.status, wraplength=1020).pack(anchor="w", pady=(0,10))
        ttk.Label(box, text="CSV内容预览（前15行，横向滚动查看全部列）").pack(anchor="w")
        table_box = ttk.Frame(box)
        table_box.pack(fill="both", expand=True)
        self.table = ttk.Treeview(table_box, show="headings", height=12)
        xs = ttk.Scrollbar(table_box, orient="horizontal", command=self.table.xview)
        ys = ttk.Scrollbar(table_box, orient="vertical", command=self.table.yview)
        self.table.configure(xscrollcommand=xs.set, yscrollcommand=ys.set)
        self.table.grid(row=0, column=0, sticky="nsew")
        ys.grid(row=0, column=1, sticky="ns")
        xs.grid(row=1, column=0, sticky="ew")
        table_box.rowconfigure(0, weight=1)
        table_box.columnconfigure(0, weight=1)
        root.after(40, self.poll)

    def choose_input(self):
        value = filedialog.askopenfilename(filetypes=[("JSON文件", "*.json"), ("所有文件", "*.*")])
        if value:
            self.source.set(value)

    def choose_output(self):
        value = filedialog.askdirectory(title="选择父目录，将在其中创建1995_转换输出")
        if value:
            self.output.set(str(Path(value) / "1995_转换输出"))

    def start(self):
        if self.running:
            return
        self.result, self.error, self.running = None, None, True
        self.convert_button.configure(state="disabled")
        self.open_button.configure(state="disabled")
        self.table.delete(*self.table.get_children())
        self.status.set("正在读取、校验并转换，请等待。")
        source, output, key = self.source.get(), self.output.get(), self.records_key.get() or None
        def work():
            try:
                self.events.put(("done", core.convert(source, output, key)))
            except Exception as exc:
                self.events.put(("error", str(exc)))
        threading.Thread(target=work, daemon=True).start()

    def poll(self):
        try:
            while True:
                kind, value = self.events.get_nowait()
                self.running = False
                self.convert_button.configure(state="normal")
                if kind == "error":
                    self.error = value
                    self.status.set(value)
                else:
                    self.result = value
                    self.status.set(f"已保存 {value['rows']} 行 / {value['columns']} 列。结果目录：{value['directory']}")
                    self.open_button.configure(state="normal")
                    with (Path(value["directory"]) / "1995_转换结果.csv").open(encoding="utf-8-sig", newline="") as handle:
                        reader = csv.reader(handle)
                        headers = next(reader)
                        self.table["columns"] = list(range(len(headers)))
                        for index, header in enumerate(headers):
                            self.table.heading(index, text=header)
                            self.table.column(index, width=160, stretch=False)
                        for _, row in zip(range(15), reader):
                            self.table.insert("", "end", values=[cell if len(cell) <= 500 else cell[:500] + "…" for cell in row])
        except queue.Empty:
            pass
        self.root.after(40, self.poll)

    def open_output(self):
        if self.result:
            os.startfile(self.result["directory"])


def self_check(source, output):
    root = tk.Tk()
    root.withdraw()
    app = Desktop(root, source, output)
    app.convert_button.invoke()
    start = time.monotonic()
    try:
        while app.running and time.monotonic() - start < 60:
            root.update()
            time.sleep(.02)
        if app.running or app.error or not app.result:
            raise ValueError(app.error or "桌面转换超时")
        assert str(app.open_button["state"]) == "normal"
        assert len(app.table.get_children()) == min(15, app.result["rows"])
        return app.result
    finally:
        root.destroy()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="1995 JSON转CSV桌面工具")
    parser.add_argument("--input", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    window = tk.Tk()
    Desktop(window, args.input, args.output)
    window.mainloop()
