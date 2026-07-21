#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
batch_extract_gui.py  —— 图形界面版，支持按文件大小过滤后批量解压

用法：
    python batch_extract_gui.py
"""
import os
import sys
import threading
from pathlib import Path
from tkinter import (
    Tk, Frame, Label, Entry, Button, Checkbutton,
    BooleanVar, StringVar, IntVar, ttk, scrolledtext
)
from tkinter import filedialog, messagebox

# 复用 CLI 版的解压核心逻辑
from batch_extract import (
    resolve_ext, supports_format, extract_archive,
    ensure_output_dir, log as log_fn
)


# ─── 工具函数 ────────────────────────────────────────────
def format_size(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    elif n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    else:
        return f"{n / 1024 / 1024:.1f} MB"


def parse_size_mb(text: str) -> float | None:
    """解析用户输入的大小（MB），空字符串返回 None"""
    s = text.strip()
    if not s:
        return None
    try:
        v = float(s)
        return v if v > 0 else None
    except ValueError:
        return None


# ─── 主窗口 ──────────────────────────────────────────────
class BatchExtractGUI:

    def __init__(self):
        self.root = Tk()
        self.root.title("批量解压工具")
        self.root.geometry("820x620")
        self.root.minsize(640, 500)
        self._build_ui()
        self._running = False

    # ── 界面搭建 ──────────────────────────────────────
    def _build_ui(self):
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(4, weight=1)  # 第5行（列表+日志）可伸缩

        # ---- 第 1 行：源文件夹 ----
        row1 = ttk.Frame(self.root, padding="8 8 8 0")
        row1.grid(row=0, column=0, sticky="ew")
        row1.columnconfigure(1, weight=1)

        ttk.Label(row1, text="源文件夹：").grid(row=0, column=0, padx=(0, 4))
        self.src_var = StringVar(value=os.getcwd())
        self.src_entry = ttk.Entry(row1, textvariable=self.src_var)
        self.src_entry.grid(row=0, column=1, sticky="ew", padx=(0, 4))
        ttk.Button(row1, text="浏览…", command=self._browse_src).grid(row=0, column=2)

        # ---- 第 2 行：选项 ----
        row2 = ttk.Frame(self.root, padding="8 4 8 0")
        row2.grid(row=1, column=0, sticky="ew")

        self.recurse_var = BooleanVar(value=True)
        ttk.Checkbutton(row2, text="递归子目录", variable=self.recurse_var).pack(side="left")

        ttk.Label(row2, text="  输出到：").pack(side="left")
        self.out_var = StringVar(value="")
        self.out_entry = ttk.Entry(row2, textvariable=self.out_var, width=28)
        self.out_entry.pack(side="left", padx=(4, 4))
        ttk.Button(row2, text="浏览…", command=self._browse_out).pack(side="left")

        # ---- 第 3 行：大小过滤 ----
        row3 = ttk.Frame(self.root, padding="8 2 8 0")
        row3.grid(row=2, column=0, sticky="ew")

        filter_f = ttk.LabelFrame(row3, text="大小过滤", padding="4 2")
        filter_f.pack(fill="x")

        ttk.Label(filter_f, text="跳过小于").pack(side="left")
        self.min_size_var = StringVar(value="")
        self.min_entry = ttk.Entry(
            filter_f, textvariable=self.min_size_var, width=7, justify="right"
        )
        self.min_entry.pack(side="left", padx=(2, 2))
        ttk.Label(filter_f, text="MB").pack(side="left")

        ttk.Label(filter_f, text="    跳过大于").pack(side="left")
        self.max_size_var = StringVar(value="")
        self.max_entry = ttk.Entry(
            filter_f, textvariable=self.max_size_var, width=7, justify="right"
        )
        self.max_entry.pack(side="left", padx=(2, 2))
        ttk.Label(filter_f, text="MB").pack(side="left")

        ttk.Separator(filter_f, orient="vertical").pack(
            side="left", fill="y", padx=(14, 10)
        )
        ttk.Label(filter_f, text="总大小：").pack(side="left")
        self.total_size_var = StringVar(value="—")
        ttk.Label(
            filter_f, textvariable=self.total_size_var, font=("", 9, "bold")
        ).pack(side="left")

        ttk.Label(filter_f, text="   匹配：").pack(side="left", padx=(10, 0))
        self.file_count_var = StringVar(value="未扫描")
        ttk.Label(filter_f, textvariable=self.file_count_var).pack(side="left")

        # ---- 第 4 行：工具栏 ----
        row4 = ttk.Frame(self.root, padding="8 4 8 0")
        row4.grid(row=3, column=0, sticky="ew")

        ttk.Button(row4, text="扫描压缩包", command=self._scan).pack(side="left")
        self.extract_btn = ttk.Button(
            row4, text="开始解压", command=self._extract, state="disabled"
        )
        self.extract_btn.pack(side="left", padx=(6, 0))

        # ---- 第 5 行：压缩包列表 + 日志（左右分栏） ----
        row5 = ttk.Frame(self.root, padding="8 4 8 4")
        row5.grid(row=4, column=0, sticky="nsew")
        row5.columnconfigure(0, weight=1)
        row5.columnconfigure(1, weight=1)
        row5.rowconfigure(0, weight=1)

        # 左侧：压缩包列表
        list_f = ttk.LabelFrame(row5, text="发现的压缩包", padding="4")
        list_f.grid(row=0, column=0, sticky="nsew", padx=(0, 4))
        list_f.columnconfigure(0, weight=1)
        list_f.rowconfigure(0, weight=1)

        self.tree = ttk.Treeview(
            list_f,
            columns=("name", "size", "status"),
            show="headings",
            height=12,
        )
        self.tree.heading("name", text="文件名")
        self.tree.heading("size", text="大小")
        self.tree.heading("status", text="状态")
        self.tree.column("name", width=280)
        self.tree.column("size", width=80, anchor="e")
        self.tree.column("status", width=80, anchor="center")
        vsb = ttk.Scrollbar(list_f, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")

        # 右侧：日志
        log_f = ttk.LabelFrame(row5, text="运行日志", padding="4")
        log_f.grid(row=0, column=1, sticky="nsew")
        log_f.columnconfigure(0, weight=1)
        log_f.rowconfigure(0, weight=1)

        self.log_text = scrolledtext.ScrolledText(
            log_f, state="disabled", wrap="word", font=("Consolas", 9), height=12
        )
        self.log_text.grid(row=0, column=0, sticky="nsew")

        # ---- 第 6 行：进度条 ----
        row6 = ttk.Frame(self.root, padding="8 0 8 8")
        row6.grid(row=5, column=0, sticky="ew")
        row6.columnconfigure(0, weight=1)

        self.progress = ttk.Progressbar(row6, mode="determinate")
        self.progress.grid(row=0, column=0, sticky="ew")
        self.progress_label = ttk.Label(row6, text="")
        self.progress_label.grid(row=0, column=1, padx=(6, 0))

    # ── 对话框回调 ────────────────────────────────────
    def _browse_src(self):
        d = filedialog.askdirectory(initialdir=self.src_var.get(), title="选择要扫描的文件夹")
        if d:
            self.src_var.set(d)
            self._scan()

    def _browse_out(self):
        d = filedialog.askdirectory(
            initialdir=self.out_var.get() or self.src_var.get(),
            title="选择解压输出根目录（留空则解压到原目录）"
        )
        if d:
            self.out_var.set(d)

    # ── 扫描 ──────────────────────────────────────────
    def _scan(self):
        self.tree.delete(*self.tree.get_children())
        self._clear_log()
        self.extract_btn.configure(state="disabled")
        self.progress["value"] = 0
        self.progress_label.configure(text="")
        self.total_size_var.set("—")

        src = Path(self.src_var.get())
        if not src.is_dir():
            messagebox.showerror("错误", f"文件夹不存在：{src}")
            return

        # 读取大小过滤条件
        min_mb = parse_size_mb(self.min_size_var.get())
        max_mb = parse_size_mb(self.max_size_var.get())

        # 收集压缩包
        if self.recurse_var.get():
            candidates = [p for p in src.rglob("*") if p.is_file()]
        else:
            candidates = [p for p in src.iterdir() if p.is_file()]

        # 汇总信息（所有能找到的压缩包，用于日志对比）
        all_found = []
        for p in candidates:
            ext = resolve_ext(p)
            if supports_format(ext):
                all_found.append(p)
        all_found.sort(key=lambda p: p.stat().st_size)
        total_all = sum(p.stat().st_size for p in all_found)

        # 按过滤条件筛选
        archives = []
        filtered_out = 0
        for p in all_found:
            size_mb = p.stat().st_size / (1024 * 1024)
            if min_mb is not None and size_mb < min_mb:
                filtered_out += 1
                continue
            if max_mb is not None and size_mb > max_mb:
                filtered_out += 1
                continue
            archives.append(p)

        self._archives = archives

        self._log(f"扫描目录：{src}")
        self._log(f"  找到压缩包：共 {len(all_found)} 个（总大小 {format_size(total_all)}）")
        if filtered_out > 0:
            self._log(f"  因大小过滤跳过：{filtered_out} 个")

        if not archives:
            self.file_count_var.set("无匹配")
            self.total_size_var.set("—")
            if all_found:
                self._log("  所有压缩包均被过滤条件排除。")
            else:
                self._log("  未发现支持的压缩包。")
            return

        total_bytes = sum(p.stat().st_size for p in archives)
        self.total_size_var.set(format_size(total_bytes))

        for arch in archives:
            size = format_size(arch.stat().st_size)
            self.tree.insert("", "end", iid=str(arch), values=(arch.name, size, "等待"))

        self.file_count_var.set(f"{len(archives)} 个")
        self._log(f"  符合条件：{len(archives)} 个，共 {self.total_size_var.get()}")
        if min_mb is not None or max_mb is not None:
            parts = []
            if min_mb is not None:
                parts.append(f"≥ {min_mb} MB")
            if max_mb is not None:
                parts.append(f"≤ {max_mb} MB")
            self._log(f"  过滤条件：{' 且 '.join(parts)}")
        self.extract_btn.configure(state="normal")

    # ── 解压 ──────────────────────────────────────────
    def _extract(self):
        if self._running:
            return
        self._running = True
        self.extract_btn.configure(state="disabled")
        self.progress["value"] = 0
        self._clear_log()

        archives = getattr(self, "_archives", [])
        if not archives:
            self._running = False
            return

        total = len(archives)
        src_root = Path(self.src_var.get())
        out_root = Path(self.out_var.get()) if self.out_var.get().strip() else None

        # 后台线程，避免阻塞界面
        def worker():
            ok = fail = skip = 0
            for idx, arch in enumerate(archives, start=1):
                if not self._running:
                    break
                rel = arch.relative_to(src_root)
                self.root.after(0, self._update_row, str(arch), "解压中…")
                self.root.after(0, self._log, f"[{idx}/{total}] {rel}  ({format_size(arch.stat().st_size)})")

                # 确定输出目录
                if out_root:
                    if arch.parent != src_root:
                        dest_base = out_root / arch.parent.relative_to(src_root)
                    else:
                        dest_base = out_root
                else:
                    dest_base = arch.parent

                dest = ensure_output_dir(dest_base, arch)
                self.root.after(0, self._log, f"    -> {dest}")

                result = extract_archive(arch, dest)
                if result:
                    ok += 1
                    self.root.after(0, self._update_row, str(arch), "✓ 成功")
                else:
                    ext = resolve_ext(arch)
                    if ext and ext[0] in ("rar", "7z"):
                        self.root.after(0, self._update_row, str(arch), "跳过")
                        self.root.after(0, self._log,
                            f"    [!] {ext[0]} 格式需额外安装：pip install patool py7zr rarfile")
                        skip += 1
                    else:
                        self.root.after(0, self._update_row, str(arch), "✗ 失败")
                        fail += 1

                self.root.after(0, self._set_progress, idx / total * 100, f"{idx}/{total}")

            self.root.after(0, self._finish, ok, fail, skip)

        threading.Thread(target=worker, daemon=True).start()

    # ── 界面更新（线程安全，通过 after 调用） ────────
    def _update_row(self, iid, status):
        if self.tree.exists(iid):
            self.tree.set(iid, "status", status)

    def _set_progress(self, value, label):
        self.progress["value"] = value
        self.progress_label.configure(text=label)

    def _log(self, msg):
        self.log_text.configure(state="normal")
        self.log_text.insert("end", msg + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _clear_log(self):
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

    def _finish(self, ok, fail, skip):
        self._running = False
        self.extract_btn.configure(state="normal")
        self.progress["value"] = 100
        self.progress_label.configure(text=f"{ok + fail + skip}/{ok + fail + skip}")
        sep = "─" * 48
        self._log("")
        self._log(sep)
        self._log(f"完成！成功：{ok}，失败：{fail}，跳过：{skip}")

    # ── 启动 ──────────────────────────────────────────
    def run(self):
        self._scan()
        self.root.mainloop()


if __name__ == "__main__":
    BatchExtractGUI().run()
