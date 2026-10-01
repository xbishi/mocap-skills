# mocap-skills

**参考视频 → Blender 骨骼动画** 的逐帧对位动捕管线，外加一个独立的红绿对位评分工具。
由 AI 编码助手（ZCode / Claude Code 等）以 skill 形式使用：读取 `SKILL.md`，按手册执行。

开发实战场：一只卡通狼从 H3 生成的走路视频学到 64 帧走路动画（全帧轮廓 IoU 均值 86%），并完成 50 帧无缝循环。

## 两个 Skill

### 1. `h3-to-blender-mocap` — 管线

把一段参考视频（AI 生成或实拍，侧视最佳）逐帧实测成骨骼动画：

- **逐帧实测**：底部轮廓下垂峰 → 触地脚位置；背线高度 → 身体波浪；头顶 → 点头
- **驱动**：脚 IK + 躯干起伏/俯仰 + 尾巴鞭状柔性摆 + 头部点头（Rigify 系 rig）
- **验证**：每帧裸渲染与参考帧算 IoU，红绿叠加图人眼验收
- **循环化**：自动扫描最优循环窗口 + 线性漂移消除闭环（帧 L+1 与帧 1 逐像素相同）

```bash
# 三条命令跑完全流程（详见 SKILL.md）
python scripts/batch_all.py
python blender_exec.py verify/_batch_k.py 600
python scripts/verify_all.py
```

### 2. `rg-mocap-score` — 独立评分工具（不依赖 Blender）

任何"模仿参考视频"的产出都能打分：参考与被测分别写进红/绿通道，重叠区自动变黄，
逐帧 IoU + 区域分解（躯干/腿）+ 红绿对比 GIF。

```bash
python rg_score.py --ref ref.mp4 --test renders --offset 8 --frames 1 64 --out score
```

| 颜色 | 含义 |
|---|---|
| 黄 | 对上了 |
| 纯红 | 参考有、你没有（没跟上） |
| 纯绿 | 你有、参考没有（多余/超前） |

## 安装

把 skill 文件夹复制到 AI 编码工具的 skills 目录：

```bash
# ZCode
cp -r h3-to-blender-mocap rg-mocap-score ~/.zcode/skills/
# Claude Code
cp -r h3-to-blender-mocap rg-mocap-score ~/.claude/skills/
```

依赖：Blender 5.1+（含 BlenderMCP addon，端口 9876）、ffmpeg/ffprobe、numpy。

## 定位与路线图

当前方法：**单目侧视剪影对位** —— 用轮廓掩码把参考视频的姿态逐帧搬进骨骼。
特点是不需要训练、不需要 3D 姿态估计模型，纯图像测量 + IK，对硬件零要求。

路线图（正在探索）：

- [ ] 任意 rig：骨骼映射从硬编码 CONFIG 改为可交换的 bone-map 描述文件
- [ ] 任意动作：跑/跳/扑已验证思路（本仓库开发过程做了 walk+run），扩展到更多动作类型
- [ ] 多视角：非正交侧视、3/4 视角下的对位
- [ ] 多方法底座：同一评分工具下对比 视频动捕（WHAM/GVHMR）/ Cascadeur / 生成式方案 的产出

## 重要经验（详见 h3-to-blender-mocap/references/pitfalls.md）

- IoU 对"藏在轮廓内部"的肢体不敏感——低 IoU 一定有错，IoU 高不代表肢体位置对
- 远侧腿在侧视图里测不到，需要"重合站立+目检分离帧"策略
- AI 生成视频的步态本身不周期，循环要靠扫描最优窗口 + 漂移消除

## License

MIT
