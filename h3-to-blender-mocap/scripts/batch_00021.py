# -*- coding: utf-8 -*-
"""H3视频→Blender 逐帧对位动捕: 全帧实测 + 逐帧贪心分配 -> targets.json -> 生成K脚本

方法与坑见 SKILL.md / references/pitfalls.md。
=======================================================================
CONFIG —— 换项目/换rig 必须逐项确认（每一项都踩过坑, 别跳）：
  1. BASE/REF_DIR/OUT_DIR  路径
  2. W,H,PX  渲染分辨率; PX = ortho_scale / W  (1px 对应世界单位)
  3. REST  前爪/后脚在参考帧1的屏幕x (静止姿势的位置, 看帧1底部轮廓峰)
  4. OFFSET  帧映射: 场景帧N = 视频帧N+OFFSET (按用户/项目约定, 别自己改)
  5. GROUND  地面线y (参考帧底部轮廓的98分位)
  6. REAR_X/FRONT_X  背线测量区间(避开尾巴与头, 取背部纯线段)
  7. 骨骼名  4脚IK / torso / hips / chest / 尾巴链 / head —— 用 dump_bones.py 查, 
     用 calibrate_bones.py 标定 local→世界方向(必须 1:1 或记录下来换算)
  8. PAIRED_PLANT  远侧腿重合站立分离帧(视频条带目检定) —— 见 pitfalls.md #4
  9. 尾巴参数  见 pitfalls.md #6 (spine_master.003 quatX + 约束置0鞭状波)
 10. 头部区域 x 区间(头顶/颈基)
=======================================================================
"""
import subprocess, numpy as np, json, sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

# ---------------- CONFIG ----------------
BASE = Path(r"H:\claude_workspace\3d_hub\projects\动作捕捉")
REF_DIR = BASE / "scripts/_gait_run20"    # 00021 奔跑·20步清晰版抽帧
OUT_DIR = BASE / "verify_00021"           # 00021 独立输出(不覆盖走路工程)
W, H = 608, 352
PX = 0.0049                               # 1px = 0.0049 世界单位 (ortho 2.977 / 608)
REST = {"front": 393.0, "rear": 211.0}    # 前爪/后脚静止位(屏幕x)
OFFSET = 14                               # 场景1=视频14(站立归位hold), 视频20(场景6)起跑                                # 场景帧N = 视频帧N+OFFSET
GROUND = 292.0                            # 地面线
BG_THR = 32                               # v2: 模糊容忍前景阈值(默认40, 奔跑模糊吃脚)
REAR_X = (160, 260)                       # 臀区背线 x 区间
FRONT_X = (330, 430)                      # 肩区背线 x 区间
LIFT = 0.32                               # v3: 奔跑抬脚更高(腾空收拢)
ROCK_SCALE = 0.6                          # v2: 摇摆实测缩放
SEG_MERGE_GAP = 25                        # 峰合并阈值(px)
PEAK_DEPTH = 8                            # 离地判定的深度(px)
PEAK_TRACK_TOL = 60                       # 轨迹追踪连续性容差(px)
TAIL_MASTER = "spine_master.003"          # 尾巴专控(quatX)
TAIL_SEGS = [("spine.002", 0.04, 1), ("spine.001", 0.05, 2), ("spine", -0.07, 3)]  # 奔跑节拍快,延迟/幅度缩小
TAIL_MASTER_AMP = 0.06                    # 慢速整体摆幅度
TAIL_MASTER_PERIOD = 28                   # 尾摆慢分量(4倍步态)                   # 慢速整体摆周期(帧)
GAIT_PERIOD = 14                          # 奔跑步态周期(20步版自相关实测)                          # 步态周期(帧, measure_freq.py 实测)
def swing_curve(t, x0, x1, lift):
    """奔跑摆动形态: x 前快后稳, z 抬高-停留-落地(非对称, 区别于走路正弦弧)"""
    te = t * t * (3 - 2 * t)
    xfrac = te * 0.75 + t * 0.25          # 前段更快到达
    x = x0 + (x1 - x0) * xfrac
    z = lift * (np.sin(np.pi * min(t, 1.0)) ** 0.7)   # 宽峰停留
    return x, z

LEG_VERT = {"front": 0.75, "rear": 0.87}    # 髋到脚的静息垂直高(标定)
MAX_REACH = {"front": 0.75, "rear": 0.88}   # 可达半径(≈腿全长, 超出必拉细/翻折)
PAIRED_PLANT = {                          # 远侧腿重合站立: (伙伴骨, 分离帧)
    "front_foot_ik.R": ("front_foot_ik.L", 24),    # 蓄力期双腿贴地,视频24(场景5)腾空
    "foot_ik.R":       ("foot_ik.L", 24),
}
FRONT_BONES = ["front_foot_ik.L", "front_foot_ik.R"]
REAR_BONES = ["foot_ik.L", "foot_ik.R"]
HEAD_NOD_SCALE = 0.21                     # head rotX+1.0 -> 头顶Δz = -0.21 (calibrate_bones 标定)
HEAD_NOD_CLIP = 0.12                      # 点头限幅(rad)
# ---------------- /CONFIG ----------------

def load_mask(vf):
    p = REF_DIR / f"g_{vf:03d}.png"
    raw = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", str(p),
                          "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                         capture_output=True, check=True).stdout
    img = np.frombuffer(raw, dtype=np.uint8).reshape(H, W, 3).astype(np.float32)
    c = 20
    pat = np.concatenate([img[:c, :c].reshape(-1, 3), img[:c, -c:].reshape(-1, 3),
                          img[-c:, :c].reshape(-1, 3), img[-c:, -c:].reshape(-1, 3)])
    bg = np.median(pat, axis=0)
    return np.linalg.norm(img - bg, axis=2) > BG_THR

def medfilt(x, k):
    pad = k // 2
    xp = np.pad(x, pad, mode='edge')
    return np.array([np.median(xp[i:i + k]) for i in range(len(x))])

def peaks(mask):
    bot = np.zeros(W)
    for x in range(W):
        col = np.nonzero(mask[:, x])[0]
        if len(col):
            bot[x] = col.max()
    b = medfilt(bot, 15)
    near = b > GROUND - 8
    out, x = [], 0
    while x < W:
        if near[x]:
            x2 = x
            while x2 < W and near[x2]:
                x2 += 1
            out.append((float((x + x2) / 2), float(b[x:x2].max())))
            x = x2
        else:
            x += 1
    merged = []
    for f in out:
        if merged and f[0] - merged[-1][0] < 25:
            if f[1] > merged[-1][1]:
                merged[-1] = f
        else:
            merged.append(f)
    return merged

# ---------- 1. 逐视频帧: 峰 + 身体中心 + 背线高度(前/后) ----------
VF = list(range(OFFSET, OFFSET + 64))    # 视频 9..72

def top_y(m, x0, x1):
    t = []
    for x in range(x0, x1):
        col = np.nonzero(m[:, x])[0]
        if len(col):
            t.append(col.min())
    return float(np.median(t)) if t else None

def smooth3(vals):
    v = np.array(vals, dtype=float)
    out = v.copy()
    for i in range(len(v)):
        lo, hi = max(0, i - 1), min(len(v), i + 2)
        out[i] = v[lo:hi].mean()
    return out

data = {}
for vf in VF:
    m = load_mask(vf)
    ys, xs = np.nonzero(m)
    data[vf] = {"peaks": peaks(m), "cx": float(xs.mean()), "cy": float(ys.mean()),
                "rear_top": top_y(m, *REAR_X), "front_top": top_y(m, *FRONT_X),
                "head_top": top_y(m, 465, 545), "neck_top": top_y(m, 415, 460),
                "back_cx": float(np.nonzero(m[60:150, :])[1].mean())}
rear_ref = data[VF[0]]["rear_top"]
front_ref = data[VF[0]]["front_top"]
head_ref = data[VF[0]]["head_top"]
neck_ref = data[VF[0]]["neck_top"]
back_cx0 = data[VF[0]]["back_cx"]
rt = smooth3([data[vf]["rear_top"] for vf in VF])
ft = smooth3([data[vf]["front_top"] for vf in VF])
ht = smooth3([data[vf]["head_top"] for vf in VF])
nt = smooth3([data[vf]["neck_top"] for vf in VF])
for i, vf in enumerate(VF):
    data[vf]["rear_top_s"] = rt[i]
    data[vf]["front_top_s"] = ft[i]
    data[vf]["head_top_s"] = ht[i]
    data[vf]["neck_top_s"] = nt[i]
print(f"视频帧 {VF[0]}..{VF[-1]} (场景1..64)")
print(f"背线基准: 臀区 top_y={rear_ref:.0f}  肩区 top_y={front_ref:.0f}  头顶={head_ref:.0f}")
dr = [-(data[vf]["rear_top_s"] - rear_ref) * PX for vf in VF]
df = [-(data[vf]["front_top_s"] - front_ref) * PX for vf in VF]
print(f"后躯起伏范围: {min(dr)*-1:+.3f}..{max(dr)*-1:+.3f} (世界Z, 相对视频9)")
print(f"前躯起伏范围: {min(df)*-1:+.3f}..{max(df)*-1:+.3f}")
print(f"前后反相性: 相关系数 {np.corrcoef(dr, df)[0, 1]:.2f} (负值=反相波浪,越负越好)")

# 头部实测点头: 头顶Δ - 颈基Δ (去掉身体起伏, 留下头部自身俯仰)
head_nod = []
for vf in VF:
    rel = (data[vf]["head_top_s"] - head_ref) - (data[vf]["neck_top_s"] - neck_ref)
    rot = rel * PX / 0.21          # 标定: head rotX+1.0 -> 头顶Δz=-0.21
    head_nod.append(round(max(-0.12, min(0.12, rot)), 4))
hn = np.array(head_nod)
print(f"头部点头: 范围 {hn.min():+.3f}..{hn.max():+.3f} rad (±{abs(hn).max():.3f})")
# 奔跑俯仰: 屏幕背线斜率(度). 正=前低后高(俯), 负=前高后低(仰)
import math
PITCH_PIVOT_BASE = 2.99      # rig 静息背线俯仰(标定探针基准)
PITCH_RAD_PER_DEG = 1.0 / 57.3 * 0.55   # v2: 渲染背线响应比探针线过冲1.8倍, 实测缩放
pitch_list = []
for vf in VF:
    th = math.degrees(math.atan2(data[vf]["front_top_s"] - data[vf]["rear_top_s"], 170.0))
    rot = (th + PITCH_PIVOT_BASE) * PITCH_RAD_PER_DEG
    pitch_list.append(round(max(-0.35, min(0.35, rot)), 4))
pl = np.array(pitch_list)
print(f"躯干俯仰: 范围 {pl.min():+.3f}..{pl.max():+.3f} rad (±{abs(pl).max():.3f})")
(OUT_DIR / "pitch.json").write_text(json.dumps(pitch_list), encoding="utf-8")

# ---------- 2. 逐帧贪心分配 ----------
FRONT = ["front_foot_ik.L", "front_foot_ik.R"]
REAR = ["foot_ik.L", "foot_ik.R"]
last = {"front": {b: None for b in FRONT}, "rear": {b: None for b in REAR}}
traj = {}          # (bone, vf) -> x
for vf in VF:
    cx = data[vf]["cx"]
    for kind, bones in (("front", FRONT), ("rear", REAR)):
        pk = sorted([x for (x, d) in data[vf]["peaks"] if (x > cx) == (kind == "front")])
        claimed = set()
        for x in pk:
            best, bestd = None, 1e9
            for b in bones:
                if b in claimed:
                    continue
                lx = last[kind][b]
                d = abs(lx - x) if lx is not None else 1e6
                if d < bestd:
                    best, bestd = b, d
            if best is None:
                continue
            claimed.add(best)
            last[kind][best] = x
            traj[(best, vf)] = x

# ---------- 3. 生成逐帧目标(摆动插值) ----------
def bone_frames(b):
    return sorted([vf for (bb, vf) in traj if bb == b])


def targets_for_bone(b, vf):
    kind = "front" if b.startswith("front") else "rear"
    if (b, vf) in traj:
        return round(-(traj[(b, vf)] - REST[kind]) * PX, 4), 0.0
    fs = bone_frames(b)
    prev = [f for f in fs if f < vf]
    nxt = [f for f in fs if f > vf]
    # ---- 远侧腿: 首次落地前跟随伙伴骨轨迹(重合站立), 分离帧后摆动到首次落地点 ----
    if not prev and b in PAIRED_PLANT and nxt:
        partner, lift = PAIRED_PLANT[b]
        f1 = nxt[0]
        x1 = traj[(b, f1)]
        if vf <= lift:
            px = traj.get((partner, vf))
            if px is not None:
                return round(-(px - REST[kind]) * PX, 4), 0.0         # 重合站立
        elif vf < f1:
            p0 = traj.get((partner, lift), REST[kind])
            t = min(max((vf - lift) / max(f1 - lift, 1), 0.0), 1.0)
            te = t * t * (3 - 2 * t)
            x = p0 + (x1 - p0) * te
            return round(-(x - REST[kind]) * PX, 4), round(float(LIFT * np.sin(np.pi * t)), 4)
    if not prev:
        if not nxt:
            return 0.0, 0.0
        f1 = nxt[0]
        x1 = traj[(b, f1)]
        span = f1 - VF[0]
        if span < 4:                      # 起步就落地: 直接站住
            return round(-(x1 - REST[kind]) * PX, 4), 0.0
        t = min(max((vf - VF[0]) / span, 0.0), 1.0)   # 首次落地前: 从 rest 摆动渐入
        x, z = swing_curve(t, REST[kind], x1, LIFT)
        return round(-(x - REST[kind]) * PX, 4), round(float(z), 4)
    f0 = prev[-1]
    x0 = traj[(b, f0)]
    if not nxt:
        # 视频结尾仍在摆动(未检测到下次落地): 从最后支撑位摆向本骨上一周期落地点
        # 例: foot_ik.R 支撑到视频59(x=99)后抬起, 摆向它上周期落点(x=248)
        fs_all = bone_frames(b)
        if fs_all:
            x_land = traj[(b, fs_all[0])]
            SWING_DUR = 14          # 典型摆动帧数(由 foot_ik.L 视频33->48 实测)
            t = min(max((vf - f0) / SWING_DUR, 0.0), 1.0)
            te = t * t * (3 - 2 * t)
            x = x0 + (x_land - x0) * te
            return round(-(x - REST[kind]) * PX, 4), round(float(LIFT * np.sin(np.pi * t)), 4)
        return round(-(x0 - REST[kind]) * PX, 4), 0.0                  # 无法推断: 保持
    f1 = nxt[0]
    x1 = traj[(b, f1)]
    if f1 <= f0:
        return round(-(x0 - REST[kind]) * PX, 4), 0.0
    t = min(max((vf - f0) / (f1 - f0), 0.0), 1.0)
    x, z = swing_curve(t, x0, x1, LIFT)
    return round(-(x - REST[kind]) * PX, 4), round(float(z), 4)

BONES = FRONT + REAR
targets = {}
REST_HOLD_END = 5   # 场景0-5=视频14-19(站立归位hold), 场景6=视频20起跑
for N in range(0, 64):
    vf = N + OFFSET
    tg = {}
    if N <= REST_HOLD_END:
        for b in BONES:
            tg[b] = (0.0, 0.0, 0.0)
        tg["torso"] = (0.0, 0.0, 0.0)
        tg["hips"] = (0.0, 0.0, 0.0)
        tg["chest"] = (0.0, 0.0, 0.0)
        targets[N] = tg
        continue
    for b in BONES:
        ly, z = targets_for_bone(b, vf)
        kind = "front" if b.startswith("front") else "rear"
        d = np.hypot(ly, z - LEG_VERT[kind])
        if d > MAX_REACH[kind]:
            k = MAX_REACH[kind] / d
            ly, z = ly * k, (z - LEG_VERT[kind]) * k + LEG_VERT[kind]
        tg[b] = (0.0, round(ly, 4), round(z, 4))
    # 身体波浪: torso=前后均值(整体起伏), hips=后躯相对, chest=前躯相对(反相)
    dz_r = -(data[vf]["rear_top_s"] - rear_ref) * PX
    dz_f = -(data[vf]["front_top_s"] - front_ref) * PX
    torso_z = (dz_r + dz_f) / 2
    rock_y = -ROCK_SCALE * (data[vf]["back_cx"] - back_cx0) * PX   # v2: 背部band质心摇摆(0.6实测缩放)
    tg["torso"] = (0.0, round(rock_y, 4), round(torso_z, 4))
    tg["hips"] = (0.0, 0.0, round(dz_r - torso_z, 4))
    tg["chest"] = (0.0, 0.0, round(dz_f - torso_z, 4))
    targets[N] = tg

# 覆盖统计
print("\n各骨覆盖帧数(有实测峰的帧):")
for b in BONES:
    print(f"  {b}: {len(bone_frames(b))}")

print("\n=== 场景帧目标抽样 (ly/z) ===")
for N in (0, 5, 13, 20, 30, 40, 50, 63):
    t = targets[N]
    print(f"帧{N:2d}(视频{N+OFFSET:2d}): " + "  ".join(
        f"{b}={v[1]:+.3f}/{v[2]:.3f}" for b, v in t.items() if b != "torso")
        + f"  torso={t['torso'][2]:+.4f}")

# ---------- 4. 导出 + 生成 K 脚本 ----------
OUT_DIR.mkdir(parents=True, exist_ok=True)
(OUT_DIR / "targets.json").write_text(
    json.dumps({str(k): v for k, v in targets.items()}, ensure_ascii=False), encoding="utf-8")

code = '''# -*- coding: utf-8 -*-
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
_old_run = bpy.data.actions.get("run")
if _old_run:
    if rig.animation_data.action == _old_run:
        rig.animation_data.action = None
    bpy.data.actions.remove(_old_run)
ad.action = bpy.data.actions.new("run")
ad.action.use_fake_user = True

T = json.load(open(r"TARGETS_JSON_PLACEHOLDER", encoding="utf-8"))
for fs, tg in T.items():
    f = int(fs)
    for bone, loc in tg.items():
        b = rig.pose.bones.get(bone)
        if b:
            b.location = loc
            b.keyframe_insert(data_path="location", frame=f)

# ---- 弯腿 pole target 常量(前肘后弯/后膝前弯, 缺了腿变直棍) ----
for f in (0, 63):
    b = rig.pose.bones["front_thigh_ik_target.L"]
    b.location = (0.0, 0.45, 0.10)   # 变体B: 奔跑杆位(防止前腿折断)
    b.keyframe_insert(data_path="location", frame=f)
    b = rig.pose.bones["thigh_ik_target.L"]
    b.location = (0.0, -0.25, 0.0)
    b.keyframe_insert(data_path="location", frame=f)

# ---- 躯干俯仰(奔跑 gallop 背线俯仰, 标定 torso quatX -57.3°/rad) ----
PITCH = json.load(open(r"PITCH_JSON_PLACEHOLDER", encoding="utf-8"))
for f in range(0, 64):
    b = rig.pose.bones["torso"]
    b.rotation_quaternion = Quaternion((1.0, 0.0, 0.0), PITCH[f])
    b.keyframe_insert(data_path="rotation_quaternion", frame=f)

# ---- 尾巴: 约束置0(关键帧) + 鞭状柔性摆动 ----
# 分层: master=慢速整体摆(周期50帧), 后三节=步态节拍延迟波(周期25帧, 延迟2/5/8帧, 尖部幅度大)
# 注意: spine 最末节局部X反向(标定), 用负号对齐世界方向
for name in ("spine.002", "spine.001", "spine"):
    b = rig.pose.bones[name]
    for c in b.constraints:
        if c.type == "COPY_ROTATION":
            c.influence = 0.0
            c.keyframe_insert(data_path="influence", frame=1)
            c.keyframe_insert(data_path="influence", frame=64)
for f in range(0, 64):
    m = rig.pose.bones["spine_master.003"]
    base_lift = 0.12 + abs(PITCH[f]) * 0.9   # 尾根上抬: 随身体俯仰联动(奔跑时尾巴水平后飘, 不下垂)
    m.rotation_quaternion = Quaternion((1.0, 0.0, 0.0), base_lift + 0.06 * math.sin(2 * math.pi * f / TAIL_MASTER_PERIOD))
    m.keyframe_insert(data_path="rotation_quaternion", frame=f)
    for name, amp, delay in (("spine.002", 0.05, 2), ("spine.001", 0.07, 5), ("spine", -0.09, 8)):
        b = rig.pose.bones[name]
        b.rotation_euler = (amp * math.sin(2 * math.pi * (f - delay) / GAIT_PERIOD), 0.0, 0.0)
        b.keyframe_insert(data_path="rotation_euler", frame=f)

# ---- 头部: 视频实测点头(头顶Δ-颈基Δ, 已标定 rotX 换算) ----
HEAD_NOD = ''' + json.dumps(head_nod) + '''
for f in range(0, 64):
    hd = rig.pose.bones["head"]
    hd.rotation_euler = (HEAD_NOD[f], 0.0, 0.0)
    hd.keyframe_insert(data_path="rotation_euler", frame=f)

sc.render.use_compositing = False
sc.render.image_settings.file_format = "PNG"
for f in range(0, 64):
    sc.frame_set(f)
    sc.render.filepath = rf"RENDER_DIR_PLACEHOLDER/bf_{f:03d}.png"
    bpy.ops.render.render(write_still=True)
sc.render.use_compositing = True
print("K+渲染完成 64帧 (含尾巴鞭状摆动+头部点头)")
'''
code = code.replace("TAIL_MASTER_PERIOD", str(TAIL_MASTER_PERIOD))
code = code.replace("GAIT_PERIOD", str(GAIT_PERIOD))
code = code.replace('(("spine.002", 0.05, 2), ("spine.001", 0.07, 5), ("spine", -0.09, 8))', str(tuple(TAIL_SEGS)))
code = code.replace("PITCH_JSON_PLACEHOLDER", str((OUT_DIR / "pitch.json")).replace(chr(92), "/"))
code = code.replace("TARGETS_JSON_PLACEHOLDER", str((OUT_DIR / "targets.json")).replace(chr(92), "/"))
code = code.replace("RENDER_DIR_PLACEHOLDER", str(OUT_DIR).replace(chr(92), "/"))
(OUT_DIR / "_batch_k.py").write_text(code, encoding="utf-8")
print("\ntargets.json + _batch_k.py 已生成")
