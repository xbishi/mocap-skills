---
name: h3-to-blender-mocap
description: H3/AI 视频 → Blender 逐帧对位动捕管线。把一段参考视频（MiniMax H3 生成或实拍）逐帧实测成骨骼动画：脚 IK 定位 + 身体前后波浪 + 尾巴柔性摆动 + 头部点头，逐帧渲染红绿对比验证。当任务涉及「给模型 K 动作/做动画/动捕/让角色学视频里的动作/侧视图对位/逐帧对齐/走跑跳动画」或用户提到 H3 视频要转成 Blender 骨骼动画、狼/动物/角色走路动画时使用。产出的动画可用 rg-mocap-score skill 评分。
---

# H3 视频 → Blender 逐帧对位动捕

把参考视频变成骨骼动画：**逐帧实测**（不是公式套）→ 驱动 IK/身体 → 渲染 **红绿对比**验证。
实测数据来自：底部轮廓下垂峰（触地脚）、背线高度（身体波浪）、头顶高度（点头）。

## 何时用

- 有一段参考视频（H3 生成的或实拍的），要让 Blender 里的角色/动物做出同样的动作
- 已有动画但"不像"：腿飘、身体僵直、幅度不对、某段腿不动
- 用户说"帮我把这个视频的动作做进 Blender / 让模型学这段动作"

## 前置环境

| 项 | 要求 |
|---|---|
| Blender | 5.1+（本文档按 5.1 的 API 写，坑见 references/pitfalls.md #1） |
| BlenderMCP | addon 挂在 9876 端口（用户 GUI 里开）；调用走 `h:/claude_workspace/3d_hub/scripts/blender_exec.py <脚本.py> [timeout]` |
| ffmpeg/ffprobe | PATH 里有（新版语法：无 `-vsync`，已改 `-fps_mode`） |
| numpy | 系统 python 有 |
| 评分工具 | 配套 skill `rg-mocap-score` |

## 五步流程

### 0. 约定（先跟用户确认，写下来别自己改）

- **帧映射**：场景帧 N = 视频帧 N+offset。offset 由用户定（可能为对齐动作起点而设），**别自作主张改**。
- **场景帧范围**、**渲染分辨率**、**活动相机**（正交侧视）、**模型网格**（视口隐藏的高模要一并关掉渲染可见性，见 pitfalls #3）。

### 1. 侦察与标定

```bash
# 骨骼地图: 找出 4脚IK / torso / hips / chest / 尾巴链 / head 的真实骨名
python scripts/dump_bones.py            # 改为经 blender_exec.py 在 Blender 内跑
# local→世界方向标定(1:1 还是带旋转, 必须实测)
python scripts/calibrate_bones.py
```
把结果写进 `batch_all.py` 的 CONFIG。**没标定过的控制骨不要动**——这个 rig 有大量陷阱（VIS_ 前缀是显示 widget、COPY_ROTATION 链上的骨直接转无效、QUATERNION 骨设 euler 无效）。

### 2. 参考视频实测（生成 targets.json）

```bash
# 抽帧（含 offset 之后需要的所有帧）
ffmpeg -loglevel error -y -i ref.mp4 -frames:v 80 scripts/_gait_tmp/g_%03d.png
# 改好 batch_all.py 顶部 CONFIG 后跑
python scripts/batch_all.py
```
产出 `verify/targets.json`（逐帧每骨 loc/抬脚）与 `verify/_batch_k.py`（可直接在 Blender 跑的 K+渲染脚本）。
关键算法：逐帧峰检测 → 按**该帧身体中心线**分前/后腿 → 同组**升序 x 贪心**分配给"上帧最近"的骨 → 摆动插值；另加 重合站立 / 结尾摆动推断 / 身体波浪 / 尾巴鞭状波 / 头部点头（全部见 references/pitfalls.md 的相邻条目）。

### 3. K 帧 + 批量裸渲染

```bash
python "h:/claude_workspace/3d_hub/scripts/blender_exec.py" verify/_batch_k.py 600
```
脚本会在 Blender 内：重建 action → K 全部帧（含 pole target 弯腿常量、尾巴约束置0+鞭状波、头点头）→ **关合成器裸渲**全帧到 `verify/bf_*.png` → 恢复合成器。
⚠️ 验证必须用**裸渲染**：合成器开着会让渲染变成红绿图，IoU 与裸渲染不可比（pitfalls #5）。

### 4. 评分（用 rg-mocap-score skill）

```bash
python "C:/Users/65681/.zcode/skills/rg-mocap-score/scripts/rg_score.py" \
  --ref ref.mp4 --test verify --offset 8 --frames 1 64 --out verify/score
```
⚠️ `--test` 是目录时要保证目录里**只有** bf_*.png（或把 bf_*.png 单独复制到子目录）。

阅读：`report.txt`（均值/最差帧/区域分解）+ `rg/` 红绿图 + `rg.gif`。
**IoU 盲区**：远侧腿藏在剪影内抬起时 IoU 不动（pitfalls #4）——腿位问题必须看红绿图或用户视口验收。

### 5. 交付与验收

- 给用户：`rg.gif`（红绿动画）+ 并排 mp4 + 逐帧 IoU 清单
- 让用户**在自己的 Blender 视口**里从任意 3D 视角播放（侧视图看不出"身体僵不僵"，见 pitfalls #7）
- 视口实时红绿叠加（可选，边 K 边看）：`setup_overlay.py`

### 6. 需要循环动画时（可选，做在验收通过之后）

**先跟用户明确**：循环必须**丢掉"待机→起步"段**（起点的双脚并立站姿在稳态步态里不会重现），循环体只能取动作稳定后的跑步机段。

```bash
python scripts/find_loop.py     # 扫 (起点A, 长度L) 找闭环代价最小的窗口
python scripts/make_loop.py A L # 闭环 + 生成循环K脚本(帧L+1=帧1) + 渲染
python "h:/claude_workspace/3d_hub/scripts/blender_exec.py" verify/_loop_k.py 600
```

关键点：

- **周期必须整除**：尾摆的慢分量周期 50、步态周期 25 → 循环长度取 50（或 25 并把尾摆改为 25）
- **闭环靠线性漂移消除**：`closed[i] = v[A+i] - (v[A+L]-v[A])·i/L`，把首尾差摊到整周期（**不要用交叉淡化**，淡化会造出"双重曝光"式浮影）；修正量应远小于周期内典型步长，否则说明循环点选错了
- **帧 L+1 复制帧 1**（逐像素相同）；Blender 场景范围设 1..L，跨接天然是一帧步长
- **验收指标**：①帧 L+1 与帧 1 渲染逐像素相同；②接缝步长 ≤ 摆动期典型步长（不是 ≤ 中位步长——多数帧脚踩地不动，中位数会被误导为 0）；③做无限循环 GIF 让人眼看接缝
- ⚠️ AI 生成视频的步态**本身不周期**（本项目自相关只有 0.35），别指望找到零代价窗口；代价最小的窗口就是最佳解

## 实时视口叠加（可选但推荐）

```bash
python "h:/claude_workspace/3d_hub/scripts/blender_exec.py" <改好路径的 setup_overlay.py> 90
```
给出：红=参考视频 / 绿=模型 / 黄=重叠，拖时间线实时刷新，摆骨骼立刻看到效果。
坑：Image 节点序列帧跟随需要三件套（source=SEQUENCE + use_auto_refresh + frame_duration，pitfalls #2）；相机上原有的视频背景图要关掉否则视口三层（pitfalls #8）。

## CONFIG 适配清单（换 rig / 换视频必做）

`batch_all.py` 顶部 CONFIG 每项都有坑，逐条对照 references/pitfalls.md：

1. 路径（BASE / REF_DIR / OUT_DIR）
2. W,H,PX（PX = ortho_scale / W）
3. REST（帧1的前爪/后脚屏幕 x）
4. OFFSET（用户约定的帧映射）
5. GROUND（帧1底部轮廓 98 分位）
6. REAR_X / FRONT_X（背线测量区间，避开尾巴和头）
7. 骨骼名（dump_bones 查）+ 标定
8. PAIRED_PLANT（远侧腿分离帧，视频条带目检定）
9. 尾巴参数（TAIL_MASTER / TAIL_SEGS / 幅度延迟）
10. 头部区域 x 区间与 HEAD_NOD_SCALE

## 参考文件

- `references/pitfalls.md` — 全部实测踩坑（API 变更 / 度量盲区 / 结尾冻结 / 约束链 / 序列帧跟随 等 15+ 条），**开工前先读**
- `references/bone_map.md` — 本机狼狐 rig 的骨骼地图与全部标定结论（当作工作范例；换 rig 用同样方法重做）
- 本机实战场：`H:/claude_workspace/3d_hub/projects/动作捕捉/`（含 PROJECT.md 全程记录，均值 86% 的成品）
