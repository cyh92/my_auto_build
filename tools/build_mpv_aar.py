#!/usr/bin/env python3
"""
构造 lib-mpvplayer-release.aar —— TV 工程 verify 校验所需的 mpv 内核 aar。

背景：
  buildSrc/AbiApkPackaging.groovy 里：
    task.mpvArchive.set(...file('libs/lib-mpvplayer-release.aar'))

  VerifyMpvNativeTask -> MpvNativeLibraries.hostLibraries() 会对这个 aar 做严格校验：
    1. libmpv.so   必须存在，且 DT_NEEDED 含 libffmpeg.so、不含拆分 libav*
    2. libplayer.so必须存在，同上，且 DT_NEEDED 必须含 libmpv.so
    3. libc++_shared.so 必须存在（用于计算 hash）

  so 来源：
    - libmpv.so / libplayer.so  -> FongMi/Release 的运行时模块 APK
                                  （runtime-mpv-*-{abi}.apk，主 APK 里没有）
    - libc++_shared.so          -> 主 APK（leanback-*.apk 里就有，模块包里没有）

用法：
  python build_mpv_aar.py \
      --mpv-apk apks/runtime-mpv-1.0.7-arm64-v8a.apk \
      --main-apk apks/leanback-arm64_v8a.apk \
      -o deps
"""

import argparse
import io
import os
import sys
import zipfile

NEED_FROM_MPV = ["libmpv.so", "libplayer.so"]
NEED_FROM_MAIN = ["libc++_shared.so"]

MANIFEST = """<?xml version="1.0" encoding="utf-8"?>
<manifest xmlns:android="http://schemas.android.com/apk/res/android"
    package="com.fongmi.aar.mpv" />
"""


def pick(apk, abi, names):
    with zipfile.ZipFile(apk) as z:
        avail = {os.path.basename(n): n for n in z.namelist()
                 if n.startswith(f"lib/{abi}/") and n.endswith(".so")}
    got, miss = {}, []
    for n in names:
        if n in avail:
            got[n] = (apk, avail[n])
        else:
            miss.append(n)
    return got, miss


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mpv-apk", required=True, help="runtime-mpv-*-{abi}.apk")
    ap.add_argument("--main-apk", required=True, help="leanback-*.apk（提供 libc++_shared.so）")
    ap.add_argument("--abi", default="arm64-v8a")
    ap.add_argument("-o", "--out-dir", default="deps")
    ap.add_argument("--name", default="lib-mpvplayer-release.aar")
    a = ap.parse_args()

    for f in (a.mpv_apk, a.main_apk):
        if not os.path.exists(f):
            sys.exit(f"文件不存在: {f}")

    got_mpv, miss_mpv = pick(a.mpv_apk, a.abi, NEED_FROM_MPV)
    got_main, miss_main = pick(a.main_apk, a.abi, NEED_FROM_MAIN)

    print(f"[{a.abi}] 来自 mpv 模块: {sorted(got_mpv)}")
    if miss_mpv:
        sys.exit(f"mpv 模块里缺: {miss_mpv}")
    print(f"[{a.abi}] 来自主 APK  : {sorted(got_main)}")
    if miss_main:
        sys.exit(f"主 APK 里缺: {miss_main}")

    sources = {**got_mpv, **got_main}
    out_path = os.path.join(a.out_dir, a.name)
    os.makedirs(a.out_dir, exist_ok=True)

    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as out:
        out.writestr("AndroidManifest.xml", MANIFEST)
        jar = io.BytesIO()
        with zipfile.ZipFile(jar, "w") as j:
            j.writestr("META-INF/MANIFEST.MF", "Manifest-Version: 1.0\r\n\r\n")
        out.writestr("classes.jar", jar.getvalue())
        out.writestr("R.txt", "")
        total = 0
        for name, (apk, entry) in sorted(sources.items()):
            with zipfile.ZipFile(apk) as z:
                data = z.read(entry)
            out.writestr(f"jni/{a.abi}/{name}", data)
            total += len(data)
            print(f"  + jni/{a.abi}/{name}  {len(data):,}")

    print(f"\n已生成 {out_path}")
    print(f"  体积 {os.path.getsize(out_path):,} B（so 合计 {total:,}）")


if __name__ == "__main__":
    main()
