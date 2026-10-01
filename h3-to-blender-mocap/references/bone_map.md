# 骨骼地图与标定结论（狼狐 rig 工作范例）

> 来源：`狼狐_动捕.blend`（Blender 5.1.2）。**换 rig 必须用同样方法重做**（`dump_bones.py` + `calibrate_bones.py`），
> 但下面这张"哪些骨是控制、哪些是陷阱"的结论可作为排查方向的参考。

## 场景

| 项 | 值 |
|---|---|
| 相机 | `right_cam`（正交 ORTHO，从 -X 看 +X；**屏幕右 = 世界 -Y**（狼头方向），屏幕上 = +Z） |
| 网格 | `狐狼`（7518 面，带 ARMATURE 修改器）；`Mesh_0`（24万面高模，**必须 hide_render**） |
| 分辨率 | 608×352，fps 24 |
| ortho_scale | 2.977 → **PX = 2.977/608 = 0.0049 世界单位/px** |
| 朝向 | 狼头朝 -Y，尾朝 +Y；近侧（面向相机）= 狼的右侧 |

## 控制骨（可用）

| 骨 | 作用 | 标定结论 |
|---|---|---|
| `foot_ik.L/R` `front_foot_ik.L/R` | 后脚/前爪主控 | **locY = 世界Y（前后步幅）、locZ = 世界Z（抬脚），1:1** |
| `front_thigh_ik_target.L/R` `thigh_ik_target.L/R` | **真 IK pole**（约束里的 pole_subtarget） | locY +0.25/-0.25 → 弯腿方向正确（前肘后弯/后膝前弯） |
| `torso` | 整体躯干 | locZ 1:1 → 世界 Z |
| `hips` | 后躯 | locZ 1:1 只动后躯（**不带动后腿**） |
| `chest` | 前躯 | locZ 1:1 只动前躯 |
| `spine_master.003` | **尾巴专控** | QUATERNION；quatX+0.1 → 尾尖Δz+0.152（链式累积），头/身不动 |
| `head` | 头 | XYZ euler；**rotX = 点头**（+0.1 → 头顶Δz-0.021）；loc 轴是斜的，纯世界Z位移需换算 |
| `neck` | 颈 | rotX+0.1 → 头顶Δz-0.012（联动小） |

## 尾巴链（需要改造才能做柔性摆动）

```
骨盆(y≈0.63) ─┬─ spine.003 → spine.002 → spine.001 → spine(尖, y≈1.14)
              └─ 每节都有 COPY_ROTATION 指向上一节，最终指向 spine_master.003
```
- 直接转 `spine/001/002/003` → **无效**（被约束覆盖）
- 只转 `spine_master.003` → 整条尾巴刚性卷动（链式累积，天然根部小尖部大）
- **要鞭状延迟波**：把 `spine.002/001/spine` 的 COPY_ROTATION `influence=0`，再逐节直接转
  - ⚠️ `spine`（末节）局部 X 反向 → 用负号
  - 实测幅度：spine.002 rxX+0.1 → 尾尖Δz+0.040；spine.001 → +0.015；spine → -0.014

## 陷阱骨（别碰/无效）

| 骨 | 真相 |
|---|---|
| `VIS_front_thigh_ik_pole.*` `VIS_thigh_ik_pole.*` | 显示 widget，改了不起作用（真 pole 是 `*_thigh_ik_target`） |
| `*_shin_tweak.*` `*_foot_tweak.*` | 小腿/脚微调，支撑腿乱动会破坏腿型（试过，负收益） |
| `tweak_spine.004/005` | 尾根 tweak，**实测对尾尖无效** |
| `MCH-ROT-tail` | COPY_ROTATION→torso，是机构骨不是控制器 |
| `DEF-*` `ORG-*` `MCH-*` | 内部机构骨，永远别动 |

## 关键常数（本项目）

```python
PX = 0.0049                # 1px = 0.0049 世界单位
REST = {"front": 393.0, "rear": 211.0}   # 静止姿势前爪/后脚屏幕 x
GROUND = 292.0             # 地面线 y
REAR_X = (160, 260)        # 臀区背线测量区间（避开尾巴）
FRONT_X = (330, 430)       # 肩区背线测量区间（避开颈/头）
HEAD_X = (465, 545)        # 头顶
NECK_X = (415, 460)        # 颈基（做头部相对量用）
OFFSET = 8                 # 场景帧 N = 视频帧 N+8（**用户约定，勿改**）
LIFT = 0.13                # 摆动抬脚峰高
```

## 步态（本项目视频实测）

- 周期 **25 帧**（`measure_freq.py` 自相关；视频 1-8 帧为静帧，动作从视频 9 起）
- 触地期脚以 ~5px/帧 匀速后滑（原地走/跑步机式）；摆动期 4-14 帧快速前迈
- 步幅峰峰：前爪 160px≈0.79、后脚 164px≈0.80（世界单位）
- 身体波浪：前后反相相关 -0.74；臀区起伏 8px、肩区 10px
