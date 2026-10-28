#!/usr/bin/env python3
"""
从官方 FongMi APK 提取 native so，打包成 TV 工程需要的 aar。

背景：
  FongMi/TV 的构建脚本硬编码要求：
    app/libs/lib-decoder-ffmpeg-release.aar  (FFmpeg 软解，so 会打进 APK) ← 本脚本负责
    app/libs/lib-mpvplayer-release.aar       (mpv 内核，so 不进 APK，仅校验) ← 无法提取，跳过校验

  官方 APK 是 ABI 拆分的（leanback-arm64_v8a.apk / leanback-armeabi_v7a.apk），
  所以每个 APK 只含一个 ABI 的 so。本脚本支持传入多个 APK，合并进同一个 aar。

用法：
  # 单个
  python extract_native_aar.py -d apks/ -o deps/
  # 指定文件
  python extract_native_aar.py -a arm64.apk -a arm32.apk -o deps/

APK 文件名 → ABI 的映射靠文件名里的 arm64_v8a / armeabi_v7a 关键字，
也支持 --abi 手动覆盖（单文件时）。
"""

import argparse
import io
import os
import re
import sys
import zipfile

# 需要提取的 so。刻意排除三个来自 Maven 依赖的，重复提取会与 Gradle 自带的冲突：
#   libavif_android.so (Glide AVIF)、libpl_droidsonroids_gif.so (android-gif-drawable)、
#   librtmp-jni.so (LibRtmp-Client-for-Android)
WANTED = [
    "libffmpeg.so",
    "libffmpegJNI.so",
    "libffmpegDoviJNI.so",
    "libmedia3ass.so",
    "libmedia3effect.so",
    "libisoJNI.so",
    "libmpeghJNI.so",
    "libcmg_decrypt.so",
    "libc++_shared.so",
]

ABI_PATTERNS = [
    (re.compile(r"arm64[_-]v8a", re.I), "arm64-v8a"),
    (re.compile(r"armeabi[_-]v7a", re.I), "armeabi-v7a"),
    (re.compile(r"x86_64", re.I), "x86_64"),
    (re.compile(r"x86", re.I), "x86"),
]

MIN_MANIFEST = """<?xml version="1.0" encoding="utf-8"?>
<manifest xmlns:android="http://schemas.android.com/apk/res/android"
    package="com.fongmi.aar.decoder" />
"""


def detect_abi(path, override=None):
    if override:
        return override
    name = os.path.basename(path)
    for pat, abi in ABI_PATTERNS:
        if pat.search(name):
            return abi
    # 兜底：看 APK 里 lib/ 下有什么
    with zipfile.ZipFile(path) as z:
        found = {n.split("/")[1] for n in z.namelist() if n.startswith("lib/") and n.count("/") >= 2}
    if len(found) == 1:
        return found.pop()
    raise SystemExit(f"无法判断 {name} 的 ABI，请用 --abi 指定（候选: {sorted(found)}）")


def collect(apk_path, abi):
    with zipfile.ZipFile(apk_path) as z:
        names = [n for n in z.namelist() if n.startswith(f"lib/{abi}/") and n.endswith(".so")]
        picked = {os.path.basename(n): n for n in names if os.path.basename(n) in WANTED}
    print(f"  [{abi}] {os.path.basename(apk_path)}: APK 内 {len(names)} 个 so，命中 {len(picked)} 个")
    missing = [w for w in WANTED if w not in picked]
    if missing:
        print(f"      未找到: {missing}")
    return picked


def build(apk_list, out_path):
    sources = {}   # abi -> {soname: (apk_path, entry)}
    for apk, abi in apk_list:
        if not os.path.exists(apk):
            sys.exit(f"APK 不存在: {apk}")
        if abi in sources:
            print(f"  ! {abi} 重复提供，忽略 {apk}")
            continue
        picked = collect(apk, abi)
        if picked:
            sources[abi] = {k: (apk, v) for k, v in picked.items()}

    if not sources:
        sys.exit("没有提取到任何 so")

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as out:
        out.writestr("AndroidManifest.xml", MIN_MANIFEST)
        jar = io.BytesIO()
        with zipfile.ZipFile(jar, "w") as j:
            j.writestr("META-INF/MANIFEST.MF", "Manifest-Version: 1.0\r\n\r\n")
        out.writestr("classes.jar", jar.getvalue())
        out.writestr("R.txt", "")

        total = 0
        for abi in sorted(sources):
            for name in sorted(sources[abi]):
                apk, entry = sources[abi][name]
                with zipfile.ZipFile(apk) as z:
                    data = z.read(entry)
                out.writestr(f"jni/{abi}/{name}", data)
                total += len(data)
                print(f"  + jni/{abi}/{name}  {len(data):,}")

    with zipfile.ZipFile(out_path) as chk:
        so_entries = [e for e in chk.namelist() if e.startswith("jni/") and e.endswith(".so")]
        abis = sorted({e.split("/")[1] for e in so_entries})

    print(f"\n已生成 {out_path}")
    print(f"  体积 {os.path.getsize(out_path):,} 字节（so 原始合计 {total:,}）")
    print(f"  覆盖 ABI: {abis}，so {len(so_entries)} 个")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-a", "--apk", action="append", default=[], help="APK 路径，可多次指定")
    ap.add_argument("-d", "--apk-dir", help="扫描该目录下所有 .apk")
    ap.add_argument("-o", "--out-dir", default="deps")
    ap.add_argument("--abi", help="单 APK 时强制指定 ABI")
    ap.add_argument("--name", default="lib-decoder-ffmpeg-release.aar")
    a = ap.parse_args()

    apks = list(a.apk)
    if a.apk_dir:
        apks += [os.path.join(a.apk_dir, f) for f in sorted(os.listdir(a.apk_dir))
                 if f.lower().endswith(".apk")]
    if not apks:
        sys.exit("请用 -a 或 -d 指定 APK")

    pairs = [(p, detect_abi(p, a.abi if len(apks) == 1 else None)) for p in apks]
    build(pairs, os.path.join(a.out_dir, a.name))


if __name__ == "__main__":
    main()
