# -*- coding: utf-8 -*-
"""rg-mocap-score 核心脚本: 红绿通道叠加对比评分

原理(与业界洋葱皮对位法同源):
  红通道 = 参考视频的亮度 × 掩码   绿通道 = 测试渲染的亮度 × 掩码   蓝通道 = 0
  红+绿=黄 => 重叠区自动变黄
  IoU = |参考掩码 ∩ 测试掩码| / |两者并集|

用法:
  python rg_score.py --ref <参考视频.mp4 或 帧目录> --test <测试帧目录 或 视频>
                     [--offset N]        # 测试帧 i 对应参考帧 i+N (默认 0)
                     [--frames A B]      # 只评这个区间(默认全部)
                     [--out DIR]         # 输出目录(默认 ./rg_out)
                     [--no-gif]          # 跳过 GIF 生成

输出:
  <out>/iou.json          逐帧 IoU
  <out>/report.txt        摘要报告(含最差帧清单 + 区域分解)
  <out>/rg/rg_XXXX.png    红绿对比帧
  <out>/rg.gif            红绿动画(便于人眼验收)

依赖: ffmpeg/ffprobe 在 PATH, numpy
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

import numpy as np

DIM = 0.25          # 掩码外亮度保留系数(淡背景参照)
BG_PATCH = 20       # 四角取样边长(px)
BG_THR = 40         # 离背景色距离阈值(判定前景掩码)
EXTS = (".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp")


# ---------------- 输入加载 ----------------

def probe_wh(video):
    out = subprocess.run(
        ["ffprobe", "-loglevel", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=p=0", str(video)],
        check=True, capture_output=True, text=True).stdout.strip()
    w, h = out.split(",")[:2]
    return int(w), int(h)


def natural_key(p: Path):
    """按文件名里最后一个数字排序(帧号), 无数字则按名字"""
    import re
    nums = re.findall(r"(\d+)", p.stem)
    return (int(nums[-1]) if nums else 0, p.name)


def frames_from_source(src: Path, glob_pat=None):
    """返回 (帧路径列表, 是否视频, 宽, 高)"""
    if src.is_dir():
        pat = glob_pat or "*"
        fs = sorted([p for p in src.glob(pat) if p.suffix.lower() in EXTS], key=natural_key)
        if not fs:
            raise SystemExit(f"目录里没有匹配的图片: {src} / {pat}")
        w, h = probe_wh(fs[0])
        return fs, False, w, h
    if src.suffix.lower() in (".mp4", ".mov", ".mkv", ".webm", ".avi"):
        w, h = probe_wh(src)
        return [src], True, w, h
    raise SystemExit(f"无法识别的输入: {src}")


def extract_video(video: Path, out_dir: Path, w, h):
    """视频抽帧为 png 序列, 返回路径列表"""
    out_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-y", "-i", str(video),
         str(out_dir / "f_%04d.png")], check=True)
    fs = sorted(out_dir.glob("f_*.png"))
    if not fs:
        raise SystemExit(f"抽帧失败: {video}")
    return fs


def load_rgb(path: Path, w, h):
    raw = subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-i", str(path),
         "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}", "-"],
        capture_output=True, check=True).stdout
    arr = np.frombuffer(raw, dtype=np.uint8)
    if arr.size != w * h * 3:
        raise SystemExit(f"{path.name}: 尺寸不符 ({arr.size} != {w*h*3}), 检查 --ref/--test 分辨率是否一致")
    return arr.reshape(h, w, 3).astype(np.float32)


def fg_mask(img):
    """前景掩码: 四角 BG_PATCH 中值当背景色, 距离 > BG_THR 为前景"""
    c = BG_PATCH
    pat = np.concatenate([img[:c, :c].reshape(-1, 3), img[:c, -c:].reshape(-1, 3),
                          img[-c:, :c].reshape(-1, 3), img[-c:, -c:].reshape(-1, 3)])
    bg = np.median(pat, axis=0)
    return np.linalg.norm(img - bg, axis=2) > BG_THR


def rg_compose(ref_img, ref_mask, test_img, test_mask):
    h, w = ref_mask.shape
    g = np.zeros((h, w, 3), dtype=np.uint8)
    g[..., 0] = np.clip(ref_img.mean(axis=2) * (ref_mask + DIM * (~ref_mask)), 0, 255)
    g[..., 1] = np.clip(test_img.mean(axis=2) * (test_mask + DIM * (~test_mask)), 0, 255)
    return g


# ---------------- 评分 ----------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ref", required=True, help="参考视频或帧目录(内容真相)")
    ap.add_argument("--test", required=True, help="测试输出帧目录或视频(被评分方)")
    ap.add_argument("--offset", type=int, default=0, help="测试帧 i ↔ 参考帧 i+offset")
    ap.add_argument("--frames", type=int, nargs=2, default=None, help="评分区间 [A B] (测试侧帧号, 1 起)")
    ap.add_argument("--out", default="rg_out", help="输出目录")
    ap.add_argument("--glob", default=None, help='测试侧图片过滤(如 "bf_*.png"), 目录混杂多套图时必填')
    ap.add_argument("--no-gif", action="store_true")
    args = ap.parse_args()

    ref_src, test_src = Path(args.ref), Path(args.test)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    rg_dir = out / "rg"
    rg_dir.mkdir(exist_ok=True)
    tmp = out / "_tmp"
    tmp.mkdir(exist_ok=True)

    ref_fs, ref_is_video, w, h = frames_from_source(ref_src)
    test_fs, test_is_video, wt, ht = frames_from_source(test_src, args.glob)
    if (w, h) != (wt, ht):
        raise SystemExit(f"分辨率不一致: ref {w}x{h} vs test {wt}x{ht}")
    if ref_is_video:
        print(f"抽帧(参考): {ref_src.name}")
        ref_fs = extract_video(ref_src, tmp / "ref", w, h)
    if test_is_video:
        print(f"抽帧(测试): {test_src.name}")
        test_fs = extract_video(test_src, tmp / "test", w, h)

    n = len(test_fs)
    a, b = (1, n) if args.frames is None else (args.frames[0], min(args.frames[1], n))
    print(f"参考 {len(ref_fs)} 帧 / 测试 {n} 帧, 评分区间 {a}-{b}, 偏移 {args.offset:+d}")

    res, tr_err, lg_err = {}, 0, 0
    tr_iou_l, lg_iou_l = [], []
    for i in range(a, b + 1):
        j = i + args.offset                      # 参考侧帧号(1 起)
        if j < 1 or j > len(ref_fs):
            print(f"  帧{i}: 对应参考帧{j} 越界, 跳过")
            continue
        ri = load_rgb(ref_fs[j - 1], w, h)
        ti = load_rgb(test_fs[i - 1], w, h)
        rm, tm = fg_mask(ri), fg_mask(ti)
        u = (rm | tm).sum()
        iou = float((rm & tm).sum() / u) if u else 0.0
        res[i] = iou

        # 区域分解: 以参考质心 y 为界(上=躯干/头, 下=腿)
        split = int(np.nonzero(rm)[0].mean()) if rm.any() else h // 2
        for sl in (slice(0, split), slice(split, h)):
            uu = (rm[sl] | tm[sl]).sum()
            v = float((rm[sl] & tm[sl]).sum() / uu) if uu else 1.0
            (tr_iou_l if sl.start == 0 else lg_iou_l).append(v)
            e = int((rm[sl] ^ tm[sl]).sum())
            if sl.start == 0:
                tr_err += e
            else:
                lg_err += e

        g = rg_compose(ri, rm, ti, tm)
        subprocess.run(
            ["ffmpeg", "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt",
             "rgb24", "-s", f"{w}x{h}", "-i", "-", str(rg_dir / f"rg_{i:04d}.png")],
            input=g.tobytes(), check=True)

    if not res:
        raise SystemExit("没有可评分的帧")

    vals = np.array(list(res.values()))
    worst = sorted(res, key=lambda k: res[k])[:5]
    lines = []
    lines.append(f"帧数 {len(vals)}   均值 {vals.mean():.1%}   中位 {np.median(vals):.1%}   "
                 f"最低 {vals.min():.1%}(帧{int(vals.argmin()) + a})   最高 {vals.max():.1%}")
    lines.append(f"区域 IoU: 躯干/头 {np.mean(tr_iou_l):.1%}   腿 {np.mean(lg_iou_l):.1%}   "
                 f"误差占比: 躯干 {tr_err / max(tr_err + lg_err, 1):.0%} / 腿 {lg_err / max(tr_err + lg_err, 1):.0%}")
    lines.append(f"最差 5 帧: {[(k, f'{res[k]:.1%}') for k in worst]}")
    lines.append("")
    lines.append("⚠️ 读数须知: IoU 对'藏在轮廓内部'的肢体不敏感(远侧腿抬起时剪影不变)——")
    lines.append("   低 IoU 一定有错, 但 IoU 高不代表肢体位置对; 必须结合 rg/ 红绿图人眼验收。")
    report = "\n".join(lines)
    print(report)

    (out / "iou.json").write_text(json.dumps({str(k): round(v, 4) for k, v in res.items()}),
                                  encoding="utf-8")
    (out / "report.txt").write_text(report, encoding="utf-8")

    if not args.no_gif and len(res) > 1:
        # 统一编号后生成 GIF
        pal = out / "_pal.png"
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-framerate", "24",
                        "-i", str(rg_dir / "rg_%04d.png"), "-vf", "palettegen", "-f", "nut", str(pal)], check=True)
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-framerate", "24",
                        "-i", str(rg_dir / "rg_%04d.png"), "-i", str(pal),
                        "-lavfi", "paletteuse", str(out / "rg.gif")], check=True)
        print(f"GIF: {out / 'rg.gif'}")

    print(f"\n输出: {out}/  (iou.json / report.txt / rg/*.png)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
