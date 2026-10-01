# -*- coding: utf-8 -*-
"""逐帧触地脚检测: 底部轮廓下垂峰(不依赖固定分区)"""
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


def medfilt(x, k):
    pad = k // 2
    xp = np.pad(x, pad, mode='edge')
    return np.array([np.median(xp[i:i + k]) for i in range(len(x))])


def feet_of_frame(mask, ground, deep=8, min_gap=25):
    """底部轮廓下垂峰 = 触地脚. 返回 [(x_center, depth), ...]"""
    bot = np.full(W, 0.0)
    for x in range(W):
        col = np.nonzero(mask[:, x])[0]
        if len(col):
            bot[x] = col.max()
    b = medfilt(bot, 15)
    near = b > ground - deep          # 接近地面的列(脚或贴地身体)
    feet = []
    x = 0
    while x < W:
        if near[x]:
            x2 = x
            while x2 < W and near[x2]:
                x2 += 1
            seg = b[x:x2]
            feet.append((int((x + x2) / 2), float(seg.max()), x2 - x))
            x = x2
        else:
            x += 1
    # 合并间距过近的(< min_gap 视为同一脚/连裆)
    merged = []
    for f in feet:
        if merged and f[0] - merged[-1][0] < min_gap:
            if f[1] > merged[-1][1]:
                merged[-1] = f
        else:
            merged.append(f)
    return merged


ground = 292.0
print("帧 | 触地脚(x中心, 深度, 宽度)  [x大=头侧]")
for fi in range(8, 44, 2):
    p = BASE / f"scripts/_gait_tmp/g_{fi+1:03d}.png"
    m = load_mask(p)
    feet = feet_of_frame(m, ground)
    s = "  ".join(f"x={f[0]:3d} d={f[1]:.0f} w={f[2]:3d}" for f in feet)
    print(f"{fi+1:3d} | {s}")
