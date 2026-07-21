#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
batch_extract.py  —— 解压指定目录下所有压缩包

用法：
    python batch_extract.py [目录路径]

如果不指定路径，默认解压当前工作目录。
支持格式：.zip .tar .tar.gz .tgz .tar.bz2 .tbz .tbz2 .tar.xz .txz .gz .bz2 .xz
"""

import os
import sys
import zipfile
import tarfile
import gzip
import bz2
import lzma
import shutil
import argparse
from pathlib import Path


def log(msg: str, indent: int = 0):
    prefix = "  " * indent
    print(f"{prefix}{msg}")


def resolve_ext(path: Path) -> list[str]:
    """
    解析文件名后缀，返回一组小写后缀名列表。
    例如 "archive.tar.gz" -> ["tar", "gz"]，"file.tbz2" -> ["tbz2"]。
    """
    name = path.name.lower()
    parts = []
    if name.endswith(".tar.gz"):
        parts = ["tar", "gz"]
    elif name.endswith(".tar.bz2"):
        parts = ["tar", "bz2"]
    elif name.endswith(".tar.xz"):
        parts = ["tar", "xz"]
    elif name.endswith(".tgz"):
        parts = ["tar", "gz"]
    elif name.endswith(".tbz") or name.endswith(".tbz2"):
        parts = ["tar", "bz2"]
    elif name.endswith(".txz"):
        parts = ["tar", "xz"]
    else:
        suffix = path.suffix.lower().lstrip(".")
        if suffix:
            parts = [suffix]
    return parts


def supports_format(suffixes: list[str]) -> bool:
    if not suffixes:
        return False
    if suffixes[0] in ("zip",):
        return True
    if suffixes[0] == "tar":
        return True
    if suffixes[0] in ("gz", "bz2", "xz"):
        return True
    return False


def extract_zip(path: Path, dest: Path) -> bool:
    try:
        with zipfile.ZipFile(path, "r") as zf:
            zf.extractall(dest)
        return True
    except zipfile.BadZipFile as e:
        log(f"  [!] 损坏的 zip 文件：{e}", indent=1)
        return False


def extract_tar(path: Path, dest: Path, mode: str = "r") -> bool:
    try:
        with tarfile.open(path, mode) as tf:
            tf.extractall(dest)
        return True
    except (tarfile.TarError, EOFError) as e:
        log(f"  [!] tar 解压失败：{e}", indent=1)
        return False


def extract_single_gz(path: Path, dest: Path) -> bool:
    """解压单个 .gz 文件（非 tar.gz）"""
    try:
        out_path = dest / path.stem
        with gzip.open(path, "rb") as fin:
            data = fin.read()
        out_path.write_bytes(data)
        return True
    except Exception as e:
        log(f"  [!] gzip 解压失败：{e}", indent=1)
        return False


def extract_single_bz2(path: Path, dest: Path) -> bool:
    """解压单个 .bz2 文件（非 tar.bz2）"""
    try:
        out_path = dest / path.stem
        with bz2.open(path, "rb") as fin:
            data = fin.read()
        out_path.write_bytes(data)
        return True
    except Exception as e:
        log(f"  [!] bzip2 解压失败：{e}", indent=1)
        return False


def extract_single_xz(path: Path, dest: Path) -> bool:
    """解压单个 .xz 文件（非 tar.xz）"""
    try:
        out_path = dest / path.stem
        with lzma.open(path, "rb") as fin:
            data = fin.read()
        out_path.write_bytes(data)
        return True
    except Exception as e:
        log(f"  [!] xz 解压失败：{e}", indent=1)
        return False


def extract_archive(path: Path, dest_dir: Path) -> bool:
    ext_parts = resolve_ext(path)
    if not ext_parts:
        return False
    if not supports_format(ext_parts):
        return False

    if ext_parts[0] == "zip":
        return extract_zip(path, dest_dir)

    if ext_parts[0] == "tar":
        if len(ext_parts) == 1:
            return extract_tar(path, dest_dir, "r:")
        compression = ext_parts[1]
        mode_map = {"gz": "r:gz", "bz2": "r:bz2", "xz": "r:xz"}
        mode = mode_map.get(compression)
        if mode is None:
            log(f"  [!] 不支持的 tar 压缩类型：{compression}", indent=1)
            return False
        return extract_tar(path, dest_dir, mode)

    if ext_parts[0] == "gz":
        return extract_single_gz(path, dest_dir)
    if ext_parts[0] == "bz2":
        return extract_single_bz2(path, dest_dir)
    if ext_parts[0] == "xz":
        return extract_single_xz(path, dest_dir)

    return False


def ensure_output_dir(base_dir: Path, archive_path: Path) -> Path:
    stem = archive_path.name
    for _ in range(3):
        p = Path(stem)
        suffix = p.suffix
        if suffix:
            stem = p.stem
        else:
            break
    if not stem:
        stem = archive_path.stem

    candidate = base_dir / stem
    if not candidate.exists():
        candidate.mkdir(parents=True, exist_ok=True)
        return candidate

    counter = 1
    while True:
        candidate = base_dir / f"{stem}_{counter}"
        if not candidate.exists():
            candidate.mkdir(parents=True, exist_ok=True)
            return candidate
        counter += 1


def scan_archives(root: Path) -> list[Path]:
    archives = []
    for entry in root.iterdir():
        if not entry.is_file():
            continue
        ext_parts = resolve_ext(entry)
        if supports_format(ext_parts):
            archives.append(entry)
    archives.sort(key=lambda p: p.stat().st_size)
    return archives


def main():
    parser = argparse.ArgumentParser(
        description="批量解压指定目录下的所有压缩包"
    )
    parser.add_argument(
        "directory", nargs="?", default=".",
        help="要扫描的目录路径（默认当前目录）"
    )
    parser.add_argument(
        "--no-recurse", action="store_true",
        help="不解压子目录中的压缩包（默认递归扫描所有子目录）"
    )
    parser.add_argument(
        "--output", "-o", default=None,
        help="解压输出根目录（默认为压缩包所在目录）"
    )
    args = parser.parse_args()

    root = Path(args.directory).resolve()
    if not root.is_dir():
        log(f"错误：目录不存在或不是文件夹 — {root}")
        sys.exit(1)

    if args.no_recurse:
        archives = scan_archives(root)
    else:
        archives = [
            p for p in root.rglob("*")
            if p.is_file() and supports_format(resolve_ext(p))
        ]
    archives.sort(key=lambda p: p.stat().st_size)

    if not archives:
        log(f"在 {root} 中未发现支持的压缩包。")
        log("支持格式：.zip .tar .tar.gz .tgz .tar.bz2 .tbz .tbz2 .tar.xz .txz .gz .bz2 .xz")
        return

    summary = {"ok": 0, "fail": 0, "skip": 0}
    for idx, arch in enumerate(archives, start=1):
        rel = arch.relative_to(root)
        size_mb = arch.stat().st_size / (1024 * 1024)
        log(f"[{idx}/{len(archives)}] {rel}  ({size_mb:.1f} MB)")

        if args.output:
            out_root = Path(args.output)
            if arch.parent != root:
                out_root = out_root / arch.parent.relative_to(root)
        else:
            out_root = arch.parent

        dest = ensure_output_dir(out_root, arch)
        log(f"    -> {dest}", indent=1)

        ok = extract_archive(arch, dest)
        if ok:
            summary["ok"] += 1
        else:
            ext_parts = resolve_ext(arch)
            if ext_parts and ext_parts[0] in ("rar", "7z"):
                log(f"    [!] 格式 {ext_parts[0]} 需额外安装库：pip install patool py7zr rarfile", indent=1)
                summary["skip"] += 1
            else:
                summary["fail"] += 1

    print()
    log("=" * 40)
    log(f"完成！成功：{summary['ok']}，失败：{summary['fail']}，跳过：{summary['skip']}")


if __name__ == "__main__":
    main()
