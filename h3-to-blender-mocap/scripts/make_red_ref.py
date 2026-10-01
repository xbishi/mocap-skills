# -*- coding: utf-8 -*-
"""H3 参考视频 -> 红通道参考视频（供 Blender 视口合成器叠加用）

复刻原版离线流程的逻辑：
  1. ffmpeg 抽帧
  2. 取四角各 corner_px 像素的颜色中值当背景色
  3. 每像素离背景色距离 > thr 即前景掩码
  4. 亮度(luma) 只写进红通道；掩码外亮度 * dim（默认 0.25）保留淡背景参照
  5. ffmpeg 编回 mp4（与场景 608x352@24fps 对齐）

用法:
  python make_red_ref.py <input.mp4> <output.mp4> [corner_px=20] [thr=40] [dim=0.25]
"""
import subprocess, sys, tempfile, shutil
from pathlib import Path
import numpy as np

sys.stdout.reconfigure(encoding="utf-8")

FFMPEG = "ffmpeg"


def extract_frames(video: Path, tmpdir: Path):
    (tmpdir / "f_%04d.png")
    cmd = [FFMPEG, "-loglevel", "error", "-i", str(video),
           str(tmpdir / "f_%04d.png")]
    subprocess.run(cmd, check=True)
    frames = sorted(tmpdir.glob("f_*.png"))
    if not frames:
        raise RuntimeError("ffmpeg 抽帧结果为空")
    return frames


def probe_wh(video: Path):
    out = subprocess.run(
        ["ffprobe", "-loglevel", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=p=0", str(video)],
        check=True, capture_output=True, text=True).stdout.strip()
    w, h = out.split(",")
    return int(w), int(h)


def frame_to_raw(p: Path, w: int, h: int) -> np.ndarray:
    cmd = [FFMPEG, "-loglevel", "error", "-i", str(p), "-f", "rawvideo",
           "-pix_fmt", "rgb24", "-s", f"{w}x{h}", "-"]
    raw = subprocess.run(cmd, check=True, capture_output=True).stdout
    return np.frombuffer(raw, dtype=np.uint8).reshape(h, w, 3).astype(np.float32)


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    src = Path(sys.argv[1])
    dst = Path(sys.argv[2])
    corner = int(sys.argv[3]) if len(sys.argv) > 3 else 20
    thr = float(sys.argv[4]) if len(sys.argv) > 4 else 40.0
    dim = float(sys.argv[5]) if len(sys.argv) > 5 else 0.25
    gain = float(sys.argv[6]) if len(sys.argv) > 6 else 1.0

    w, h = probe_wh(src)
    tmpdir = Path(tempfile.mkdtemp(prefix="redref_"))
    try:
        frames = extract_frames(src, tmpdir)
        n = len(frames)
        print(f"视频 {src.name}: {w}x{h}, {n} 帧")

        out_dir = tmpdir / "out"
        out_dir.mkdir()
        fg_ratios = []
        bg_color = None
        for i, fp in enumerate(frames, 1):
            img = frame_to_raw(fp, w, h)
            # 四角各 corner 像素 -> 颜色中值当背景色
            c = corner
            patches = np.concatenate([
                img[:c, :c].reshape(-1, 3), img[:c, -c:].reshape(-1, 3),
                img[-c:, :c].reshape(-1, 3), img[-c:, -c:].reshape(-1, 3)])
            bg = np.median(patches, axis=0)  # (3,)
            if bg_color is None:
                bg_color = bg
            dist = np.linalg.norm(img - bg, axis=2)
            mask = dist > thr  # 前景掩码
            fg_ratios.append(float(mask.mean()))
            luma = img.mean(axis=2)
            # 掩码内全额、掩码外 x dim —— 只进红通道
            r = np.clip(luma * (mask + dim * (~mask)) * gain, 0, 255)
            out = np.zeros((h, w, 3), dtype=np.uint8)
            out[..., 0] = np.clip(r, 0, 255)
            # 写回 png（用 ffmpeg rawvideo->png，零依赖）
            subprocess.run(
                [FFMPEG, "-loglevel", "error", "-f", "rawvideo", "-pix_fmt",
                 "rgb24", "-s", f"{w}x{h}", "-i", "-", str(out_dir / f"o_{i:04d}.png")],
                input=out.tobytes(), check=True)

        print(f"背景色中值 = {bg_color.round(1)}  前景占比 min/avg/max = "
              f"{min(fg_ratios):.1%} / {sum(fg_ratios)/n:.1%} / {max(fg_ratios):.1%}")

        subprocess.run(
            [FFMPEG, "-loglevel", "error", "-y", "-framerate", "24", "-i",
             str(out_dir / "o_%04d.png"), "-c:v", "libx264", "-pix_fmt",
             "yuv420p", "-crf", "18", str(dst)], check=True)
        print(f"输出: {dst}  ({dst.stat().st_size/1024:.0f} KB)")

        # 保留 PNG 序列目录（Blender 合成器里帧跟随比 mp4 更可靠）
        seq_dir = dst.with_name(dst.stem + "_frames")
        if seq_dir.exists():
            shutil.rmtree(seq_dir)
        shutil.copytree(out_dir, seq_dir)
        print(f"序列: {seq_dir}  ({n} 张)")

        # 预览条: 均匀取 6 帧横拼
        idx = np.linspace(1, n, 6).round().astype(int)
        tiles = []
        for j in idx:
            tiles.append(frame_to_raw(out_dir / f"o_{j:04d}.png", w, h).astype(np.uint8))
        strip = np.concatenate(tiles, axis=1)
        prev = dst.with_name(dst.stem + "_preview.png")
        subprocess.run(
            [FFMPEG, "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt",
             "rgb24", "-s", f"{w*6}x{h}", "-i", "-", str(prev)],
            input=strip.tobytes(), check=True)
        print(f"预览: {prev}")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    main()
