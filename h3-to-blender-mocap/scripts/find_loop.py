# -*- coding: utf-8 -*-
"""找最佳循环点: 扫描 (起点A, 长度L), 用各通道闭环代价最小者
闭环代价 = 各通道 |v(A+L) - v(A)| 归一化之和 (越小说明该处越接近自然闭合)
"""
import json, sys
import numpy as np
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
BASE = Path(r"H:\claude_workspace\3d_hub\projects\动作捕捉")
T = json.load(open(BASE / "verify/targets.json", encoding="utf-8"))
HN = json.load(open(BASE / "verify/head_nod.json", encoding="utf-8"))

BONES = ["front_foot_ik.L", "front_foot_ik.R", "foot_ik.L", "foot_ik.R",
         "torso", "hips", "chest"]
N_FRAMES = 64

# 通道矩阵: (通道数, 64)
series = {}
for b in BONES:
    series[f"{b}.y"] = np.array([T[str(f)][b][1] for f in range(1, N_FRAMES + 1)])
    series[f"{b}.z"] = np.array([T[str(f)][b][2] for f in range(1, N_FRAMES + 1)])
series["head.nod"] = np.array(HN[:N_FRAMES])

# 归一化尺度: 每通道的典型帧间步长(避免大行程通道主导)
scales = {k: max(np.median(np.abs(np.diff(v))), 1e-4) for k, v in series.items()}

def cost(A, L):
    """A: 起点场景帧(1起); L: 循环长度(帧)"""
    if A < 1 or A + L > N_FRAMES + 1:
        return None
    tot = 0.0
    for k, v in series.items():
        i0, i1 = A - 1, A - 1 + L
        if i1 >= len(v):
            return None
        tot += abs(v[i1] - v[i0]) / scales[k]
    return tot

print("扫描循环点 (代价=闭环需要修的漂移量, 单位=典型帧步长倍数):")
print("  A\\L " + "".join(f"{L:>7d}" for L in (20, 25, 30, 37, 40, 50)))
best = []
for A in range(1, N_FRAMES - 20):
    row = f"  帧{A:2d}"
    for L in (20, 25, 30, 37, 40, 50):
        c = cost(A, L)
        row += f"{c:7.1f}" if c is not None else "      -"
        if c is not None:
            best.append((c, A, L))
    if A <= 20 or A % 5 == 0:
        print(row)

best.sort()
print("\n最优 10 个 (代价, 起点场景帧, 长度):")
for c, A, L in best[:10]:
    print(f"  代价{c:5.1f}  起点帧{A}(视频{A+8})  长度{L}帧")

# 推荐: 长度优先 25/50 (尾摆周期整除), 再取代价最小
for pref in (50, 25):
    cand = [x for x in best if x[2] == pref]
    if cand:
        c, A, L = cand[0]
        print(f"\n推荐(长度{L}): 起点场景帧 {A} (视频{A+8}) -> {A+L-1} (视频{A+L+7})  代价 {c:.1f}")
