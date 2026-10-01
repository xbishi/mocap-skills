# -*- coding: utf-8 -*-
"""实测视频步频: 相邻帧掩码XOR面积时序的自相关周期"""
import subprocess, numpy as np
from pathlib import Path

BASE = Path(r"H:\claude_workspace\3d_hub\projects\动作捕捉")
W, H = 608, 352


def load_mask(p):
    raw = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", str(p),
                          "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                         capture_output=True, check=True).stdout
    img = np.frombuffer(raw, dtype=np.uint8).reshape(H, W, 3).astype(np.float32)
    c = 20
    patches = np.concatenate([img[:c, :c].reshape(-1, 3), img[:c, -c:].reshape(-1, 3),
                              img[-c:, :c].reshape(-1, 3), img[-c:, -c:].reshape(-1, 3)])
    bg = np.median(patches, axis=0)
    return np.linalg.norm(img - bg, axis=2) > 40


frames = sorted((BASE / "scripts/_gait_tmp").glob("g_*.png"))
masks = [load_mask(p) for p in frames]
n = len(masks)
# 相邻帧变化面积（动作强度代理）
d = np.array([(masks[i] ^ masks[i + 1]).sum() for i in range(n - 1)], dtype=float)
print("相邻帧变化面积(动作强度):")
for i in range(0, n - 1, 4):
    bar = '#' * int(d[i] / 60)
    print(f"  帧{i+1:3d}-{i+2:3d}: {d[i]:5.0f} {bar}")

# 动作起始帧
act_start = next((i + 1 for i, v in enumerate(d) if v > d.max() * 0.15), 1)
print(f"\n动作起始帧 ≈ {act_start}")

# 自相关（动作段）
seg = d[act_start:] - d[act_start:].mean()
if len(seg) > 20 and seg.std() > 1:
    ac = np.correlate(seg, seg, 'full')[len(seg) - 1:]
    ac /= ac[0]
    # 找 5..40 帧范围内的峰
    lo, hi = 5, min(40, len(ac) - 1)
    lags = np.argsort(-ac[lo:hi])[:5] + lo
    print(f"自相关峰 lag(帧): {sorted(lags.tolist())}")
    print(f"最强周期 = {lags[0]} 帧 ({lags[0]/24:.2f}s)  ac={ac[lags[0]]:.3f}")
    # 半周期峰（对角步态: 一次脚交换=半周期）
    half = np.argsort(-ac[lo:hi])[:5] + lo
    print(f"候选周期: {[f'{l}帧(ac={ac[l]:.2f})' for l in sorted(half.tolist())]}")
