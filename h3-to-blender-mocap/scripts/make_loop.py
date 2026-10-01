# -*- coding: utf-8 -*-
"""make_loop.py —— 把逐帧对位动画变成无缝循环

原理:
  1. 从稳态段取一个循环窗口 [A, A+L)  (find_loop.py 扫描最优)
  2. 各通道"线性漂移消除"闭环: closed[i] = v[A+i] - (v[A+L]-v[A]) * i/L
     => closed[0] == closed[L], 首尾严格相接(漂移被摊到整个周期, 不产生突兀跳变)
  3. 帧 L+1 复制帧 1 (Blender 循环播放 1..L, 跨接天然一帧步长)
  4. 尾巴/头部的周期量按 A 换算相位, 保证整除闭合(25|50, 50|50)

用法:
  python scripts/make_loop.py [A] [L]
  默认 A=10, L=50 (find_loop.py 扫描得到的最优: 场景帧10-59)
"""
import json, sys
import numpy as np
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
BASE = Path(r"H:\claude_workspace\3d_hub\projects\动作捕捉")
OUT = BASE / "verify"

A = int(sys.argv[1]) if len(sys.argv) > 1 else 10      # 起点场景帧(1起)
L = int(sys.argv[2]) if len(sys.argv) > 2 else 50      # 循环长度(帧)

T = json.load(open(OUT / "targets.json", encoding="utf-8"))
HN = json.load(open(OUT / "head_nod.json", encoding="utf-8"))

BONES = ["front_foot_ik.L", "front_foot_ik.R", "foot_ik.L", "foot_ik.R",
         "torso", "hips", "chest"]

def close_series(v):
    """线性漂移消除: 输入长度 L+1 (含闭合端点), 输出长度 L"""
    d = v[-1] - v[0]
    out = np.array([v[i] - d * i / (len(v) - 1) for i in range(len(v) - 1)])
    return out

# 场景帧 A .. A+L (共 L+1 个点)
scene_frames = list(range(A, A + L + 1))

loop_targets = {i + 1: {} for i in range(L + 1)}     # 循环帧 1..L+1
for b in BONES:
    for ch, idx in (("y", 1), ("z", 2)):
        v = np.array([T[str(f)][b][idx] for f in scene_frames], dtype=float)
        cv = close_series(v)
        for i in range(L):
            loop_targets[i + 1][b] = list(loop_targets[i + 1].get(b, [0.0, 0.0, 0.0]))
            loop_targets[i + 1][b][idx] = round(float(cv[i]), 4)
        # 帧 L+1 == 帧 1
        loop_targets[L + 1][b] = list(loop_targets[1][b])

hn = np.array([HN[f - 1] for f in scene_frames], dtype=float)
hn_c = close_series(hn)
head_loop = [round(float(x), 4) for x in hn_c] + [round(float(hn_c[0]), 4)]

# 闭环质量: 首尾步长 vs 典型步长
print(f"循环窗口: 场景帧 {A}-{A+L} (视频 {A+8}-{A+L+8}), 输出循环帧 1-{L+1}")
print("闭环质量(首尾接缝步长 / 周期内典型步长, 越接近 1 越平滑):")
worst = []
for b in BONES:
    for ch, idx in (("y", 1), ("z", 2)):
        v = np.array([loop_targets[i + 1][b][idx] for i in range(L + 1)])
        typical = np.median(np.abs(np.diff(v[:L])))
        # 接缝 = 帧L -> 帧1 的步长(周期函数在 L+1 处等于 1)
        seam = abs(v[L] - v[L - 1])
        ratio = seam / typical if typical > 1e-6 else 1.0
        worst.append((ratio, f"{b}.{ch}", typical, seam))
worst.sort(reverse=True)
for r, name, typ, seam in worst[:6]:
    flag = "  ⚠️" if r > 3 else ""
    print(f"  {name:22s} 比值 {r:5.2f} (典型步长 {typ:.4f}, 接缝步长 {seam:.4f}){flag}")

# 导出
(OUT / "targets_loop.json").write_text(
    json.dumps({str(k): v for k, v in loop_targets.items()}, ensure_ascii=False), encoding="utf-8")
(OUT / "head_nod_loop.json").write_text(json.dumps(head_loop), encoding="utf-8")

# 生成循环 K 脚本 (尾巴相位按 A 换算, 保证周期整除)
TAIL_SEGS = [("spine.002", 0.05, 2), ("spine.001", 0.07, 5), ("spine", -0.09, 8)]
segs_str = json.dumps(TAIL_SEGS)
code = '''# -*- coding: utf-8 -*-
"""循环版 K: 帧 1-''' + str(L + 1) + ''' (帧 ''' + str(L + 1) + ''' = 帧 1), 场景范围 1-''' + str(L) + '''"""
import bpy, json, math
from mathutils import Quaternion
sc = bpy.context.scene
rig = bpy.data.objects.get("rig")
ad = rig.animation_data or rig.animation_data_create()
if ad.action:
    old = ad.action
    ad.action = None
    if old.users == 0:
        bpy.data.actions.remove(old)
ad.action = bpy.data.actions.new("walk_loop_''' + str(L) + '''")
ad.action.use_fake_user = True

T = json.load(open(r"''' + str((OUT / "targets_loop.json")).replace(chr(92), "/") + '''", encoding="utf-8"))
for fs, tg in T.items():
    f = int(fs)
    for bone, loc in tg.items():
        b = rig.pose.bones.get(bone)
        if b:
            b.location = loc
            b.keyframe_insert(data_path="location", frame=f)

# 弯腿 pole target 常量
for f in (1, ''' + str(L + 1) + '''):
    b = rig.pose.bones["front_thigh_ik_target.L"]
    b.location = (0.0, 0.25, 0.0)
    b.keyframe_insert(data_path="location", frame=f)
    b = rig.pose.bones["thigh_ik_target.L"]
    b.location = (0.0, -0.25, 0.0)
    b.keyframe_insert(data_path="location", frame=f)

# 尾巴: 约束置0 + 鞭状柔性摆动 (相位按场景帧 A-1+i 换算, 周期 25/50 整除 L=50)
for name in ("spine.002", "spine.001", "spine"):
    b = rig.pose.bones[name]
    for c in b.constraints:
        if c.type == "COPY_ROTATION":
            c.influence = 0.0
            c.keyframe_insert(data_path="influence", frame=1)
            c.keyframe_insert(data_path="influence", frame=''' + str(L + 1) + ''')
A = ''' + str(A) + '''
SEGS = ''' + segs_str + '''
for i in range(1, ''' + str(L + 2) + '''):
    sf = A - 1 + i            # 对应原场景帧(用于相位)
    m = rig.pose.bones["spine_master.003"]
    m.rotation_quaternion = Quaternion((1.0, 0.0, 0.0), 0.06 * math.sin(2 * math.pi * sf / 50.0))
    m.keyframe_insert(data_path="rotation_quaternion", frame=i)
    for name, amp, delay in SEGS:
        b = rig.pose.bones[name]
        b.rotation_euler = (amp * math.sin(2 * math.pi * (sf - delay) / 25.0), 0.0, 0.0)
        b.keyframe_insert(data_path="rotation_euler", frame=i)

# 头部: 闭环后的实测点头
HEAD_NOD = ''' + json.dumps(head_loop) + '''
for i in range(1, ''' + str(L + 2) + '''):
    hd = rig.pose.bones["head"]
    hd.rotation_euler = (HEAD_NOD[i - 1], 0.0, 0.0)
    hd.keyframe_insert(data_path="rotation_euler", frame=i)

sc.frame_start, sc.frame_end = 1, ''' + str(L) + '''
sc.render.use_compositing = False
sc.render.image_settings.file_format = "PNG"
for f in range(1, ''' + str(L + 2) + '''):
    sc.frame_set(f)
    sc.render.filepath = rf"''' + str(OUT).replace(chr(92), "/") + '''/loop_{f:03d}.png"
    bpy.ops.render.render(write_still=True)
sc.render.use_compositing = True
sc.frame_set(1)
print("循环版 K+渲染完成: ''' + str(L + 1) + ''' 帧 (帧''' + str(L + 1) + '''=帧1)")
'''
(OUT / "_loop_k.py").write_text(code, encoding="utf-8")
print(f"\n已生成: targets_loop.json / head_nod_loop.json / _loop_k.py")
print(f"下一步: python h:/claude_workspace/3d_hub/scripts/blender_exec.py verify/_loop_k.py 600")
