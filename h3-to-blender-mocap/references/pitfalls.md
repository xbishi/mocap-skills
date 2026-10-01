# 踩坑清单（全部实测，血泪版）

按"会浪费你最多时间"排序。**开工前通读一遍**。

## 1. Blender 5.1 API 大改（会直接报 AttributeError）

| 旧写法（3.x/4.x 教程里的） | 5.1 正确写法 |
|---|---|
| `scene.node_tree` | `scene.compositing_node_group`（指向 `CompositorNodeTree`） |
| `CompositorNodeMath` / `CompositorNodeValue` / `CompositorNodeComposite` / `CompositorNodeRGBToBW` | **已删除**；改用统一节点 `ShaderNodeMath` / `ShaderNodeValue`，输出用 `NodeGroupOutput` + `tree.interface.new_socket(...)` |
| `action.fcurves` | `action.layers[].strips[].channelbags[].fcurves` |
| `camera.background_images.new(image=img)` | `new()` 不带参，再 `bg.image = img` |
| Image 节点 `node.image_user.*` | 帧属性直接在节点上：`node.use_auto_refresh` / `node.frame_duration` / `node.frame_offset` |

## 2. 序列帧跟随"三件套"缺一不可（缺一个就永远渲染第 1 帧）

```python
img.source = 'SEQUENCE'        # 只 load() 一张 png 得到的是 FILE，不扫目录
node.use_auto_refresh = True
node.frame_duration = N        # 不显式设，渲染管线钳在第1帧；GUI里 frame_set 有时才触发扫描
```

## 3. 视口隐藏 ≠ 渲染隐藏

Rodin 之类生成的高模（本项目 `Mesh_0`，24 万面）常常**视口里 hide 了但 `hide_render` 还是 False**，
于是每帧渲染都多画一个静止的高模 → 红绿图变三层。开工先扫：

```python
for o in bpy.data.objects:
    if o.type == 'MESH' and o.hide_get() and not o.hide_render:
        o.hide_render = True
```

## 4. 远侧腿必须"重合站立"——分离帧要用视频条带目检定

侧视图里远侧腿被身体挡住**测不到**。若直接让它从静止位开始摆动，会出现"帧 1-12 右后腿悬空"（用户一眼看出）。
正确做法：远侧腿在**首次落地前踩在近侧腿的实测轨迹上**（视频里两爪本就重叠），到**分离帧**才抬起摆动。
分离帧不能猜（按峰宽变窄猜会错 2-3 帧），用**视频条带逐帧目检**：

```bash
ffmpeg -loglevel error -y -i g_%03d.png -vf "select='between(n,13,24)',crop=200:120:60:180,scale=400:240,tile=6x2" \
  -frames:v 1 -fps_mode passthrough rear_strip.png
```
看爪子何时离地（深色脚底可见即已抬起）。本项目实测：前.R 分离@10、后.R 分离@16。

## 5. 度量污染：合成器开着时渲染会变红绿图

红绿图的掩码 IoU 天然比裸渲染低 ~15pt，两者**不可混比**。
验证一律：`sc.render.use_compositing = False` → 渲染 → 恢复 `True`。
另：**红绿图只能从裸渲染生成**，拿红绿图再叠一次红绿会产生"三个影子"。

## 6. 尾巴：COPY_ROTATION 链 + 专控骨

- 尾巴链 `spine.003←spine.002←spine.001←spine` 上都有 COPY_ROTATION（朝 `spine_master.003`），**直接转 tail 骨无效**
- **`spine_master.003` quatX 是尾巴专控**：+0.1 → 尾尖Δz+0.152（链式累积放大），头/身不动。
  曾经转 0.5 以为"全身崩"，其实是**尾巴甩过天**——判断影响范围要看头/脚的位移，别只看 IoU
- **鞭状柔性摆动**：把 `spine.002/001/spine` 的 COPY_ROTATION `influence=0`（关键帧@首末帧），再逐节直接转，
  延迟 2/5/8 帧、幅度 0.05/0.07/0.09（尖大根小）
- ⚠️ **最末节 `spine` 的局部 X 方向是反的**（标定得到），要用负号对齐世界方向
- 恢复 rig 默认：把那三根骨的 influence 改回 1 并删关键帧

## 7. 侧视图验证不了"身体僵不僵"

用户从第三方视角看才会发现"身体没起伏、不像走路"。身体波浪必须显式做：
- 逐帧测背线（臀区/肩区轮廓顶部中值，3 帧平滑）→ `torso.locZ`=均值、`hips.locZ`=后躯相对、`chest.locZ`=前躯相对
- 已标定：`hips.locZ` 只动后躯（腿不动）、`chest.locZ` 只动前躯、`torso` 都动，均 1:1
- 视频实测前后反相相关 -0.74（后躯升时前躯降）——这是"走路感"的来源

## 8. 视口三层 & 相机缩放

- 相机上原来挂的参考视频背景图（alpha 0.5 那张）在合成器启用后会成为**第三层**，必须 `show_background_image = False`
- 相机视口被 `view_camera_zoom` 缩放过后，看红绿图会误判"比例不对"。`view_camera_zoom=0`/offset=(0,0) 复位

## 9. 骨骼命名陷阱

- `VIS_*` 前缀的是**显示 widget**，不是控制器（改了不起作用）
- 真 IK pole 是约束里 `pole_subtarget` 指向的那根（本项目是 `*_thigh_ik_target`）
- pole 悬在脚正上方 → IK 解成**直棍腿**（静帧看不出来，动起来全错）。本项目：前腿 pole 后移 +0.25、后腿前移 -0.25
- `spine_master.003` 是 QUATERNION 模式，**设 rotation_euler 无效**
- `head` 骨 loc 轴是斜的（local Y/Z 都含世界 Z 分量），要做纯世界 Z 位移需联立换算

## 10. 带 action 时手调姿势会被覆盖

标定/试验脚本要先 `rig.animation_data.action = None`，完事还原，否则 `frame_set`/刷新会把姿势打回关键帧值（表现为"标定全是零位移"）。

## 11. 度量盲区：IoU 看不见剪影内部的肢体

远侧腿抬起时藏在身体轮廓内，IoU 只波动 ±1%，但人眼一眼看出"腿飘着"。
**低 IoU 一定有错，IoU 高不代表肢体位置对**——腿位修正必须看红绿图/视口。
（本项目两次踩：直棍腿、悬空腿，IoU 都没报警。）

## 12. 视频结尾"腿被冻住"

某条腿的支撑段在视频中途结束后，若视频里它还在摆但**没有新落地点被检测到**，旧代码"无下一段则保持"会把它冻结在原地。
修法：从最后支撑位**摆向本骨上一周期的落地点**（`traj[(b, 首段首帧)]`），时长取实测（本项目 14 帧）。

## 13. 峰检测与腿位分配（试错最多的地方）

- ❌ 固定 x 阈值分前/后腿 → 边界漂移（前腿后蹬可到 300、后腿前摆可到 270，区间重叠）
- ❌ 固定分区比例 → 步幅被截断（真实峰峰 160px）
- ❌ 按段均值分类 + 时间序交替 L/R → 峰合并/碎片导致交替错乱
- ✅ **每帧身体中心线分类 + 同组升序 x 贪心（取上帧最近值）** → 正确处理落地/离地
- 侧视图里 L/R 名义互换不影响剪影（正交投影），但影响"哪条腿在前"，交付时说明清楚

## 14. 文件转义与工具选择

- MCP 通道（socket）里中文路径 + Windows 反斜杠极易被吃（`\3d` `\v` 变控制字符）——**用 Write 工具写脚本文件，别在 bash 里拼 python 代码**
- 生成的脚本内路径统一用**正斜杠**（Blender 在 Windows 接受）
- 大数组别塞进 MCP 代码字符串（几百行会爆）——写 JSON 文件让 Blender 侧读

## 15. ffmpeg 新语法

- `-vsync` 已改名 `-fps_mode`（`-vsync 0` → `-fps_mode passthrough`）
- 探测分辨率用 `ffprobe`（不是 `ffmpeg -show_entries`）
- 抽帧：`ffmpeg -i in.mp4 -frames:v N out_%03d.png`

## 16. Blender 5.1 里 `Action.fcurves` 没了

清空旧动画别遍历 fcurves 删除，直接删 action 重建：

```python
ad = rig.animation_data or rig.animation_data_create()
if ad.action:
    old = ad.action; ad.action = None
    if old.users == 0: bpy.data.actions.remove(old)
ad.action = bpy.data.actions.new("my_action")
```

## 17. 帧映射偏移是"用户的约定"，不是 bug

用户的 `frame_offset`（场景帧 N = 视频帧 N+offset）是经过对齐调好的。**不要"修正"它**，也不要留测试残留
（本项目曾把偏移停在 +8 忘归零，导致"红色对不上"误判）。改过偏移必须验证归位。

## 18. 关键帧要 K 全帧，不要只 K 关键姿态

侧视对位动画靠的是"每帧都贴实测值"；只在几个姿态上 K 再插值，中间帧必然漂。
本项目做法：逐帧 K（64 帧 × 每骨每帧一个关键帧），曲线近乎线性，效果最好。

## 19. NInfer/其他大模型通道的边界

本管线不含大模型；若上游的参考视频由 H3 等生成，注意：**H3 视频的步频会漂移**（自相关只有 0.35），
逐帧贴它反而会抖。做法：以实测周期（`measure_freq.py`）为骨架，逐帧微调，别强行 100% 贴。

## 20. Action 卫生（多动作并存的正确姿势）

- **换动作 ≠ 清空旧动作**：Action 是可并存的资产（walk/run/loop 各一条随时切换），要清的是"姿势"不是"动作"
- **姿势残留**：姿势数据独立于 Action 存在——新 Action 没覆盖的骨骼通道会保留上次手摆的值。K 新动作前先把全部控制骨复位（loc=(0,0,0)、quat=identity；手动则是 Alt+G/R/S）
- **每动作一个 Action + `use_fake_user=True`**：不挂 fake user 的 Action 存档即丢
- **完成后清理中间版本**：迭代会堆出 `walk_fbf_v3.001` 这类副本（.002/.003 是同名重建时的自动尾缀），交付前按保留清单删除 + `bpy.data.orphans_purge()`
- **删除后访问数据块会炸**：`bpy.data.actions.remove(a)` 之后再读 `a.name` 报 "StructRNA has been removed"——先取名字再删

## 21. Blender MCP 会话的 import 缓存

经 `blender_exec.py` 在 Blender 里 `import 某脚本` 后，该模块**缓存在 Blender 会话的 sys.modules 里**。
之后修改了脚本文件再 import，拿到的还是**旧代码**（表现为"补丁明明写了、跑出来还是旧行为"）。
修法：运行器里强制 `importlib.reload(模块)`，或每次用不同的模块名。
（本项目实测：switch_overlay.py 改了 offset 后切换，三次都拿到旧值，reload 后才生效。）

## 22. IK_Stretch 与可达性钳制（腿部形态两大开关）

- **腿被拉细** = Rigify `thigh_parent.L/R`、`front_thigh_parent.L/R` 上的自定义属性 `IK_Stretch = 1`（目标超出腿长时腿拉橡皮去够）。修法：四腿设 0（rig 级开关，持久保存，所有动作共用）
- **前腿折断/翻折** = 目标超出可达半径 + 杆向量位置不适配。修法：**目标可达性钳制**——每帧算脚目标到髋的距离，超过腿自然伸展长度就拉回边界（数学上杜绝拉伸与翻折，代价是极远帧爪子差几像素）
- 参考数值（本狼）：肩高 z0.78、髋高 z0.90、可达半径 front 0.75 / rear 0.88（世界单位，PX=0.0049）
- 权重问题 vs 姿势问题的判别：权重缺陷**帧帧存在**（静态绑定数据）；随帧出现的形变问题在姿势/IK 层
