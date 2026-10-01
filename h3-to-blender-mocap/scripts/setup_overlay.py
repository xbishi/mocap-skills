# -*- coding: utf-8 -*-
"""红绿对位 · 视口合成器一键搭建/还原（Blender 5.1 · 狼狐_动捕）

用法 A（推荐）：Blender GUI 里 Scripting 标签打开本文件，改好 MOCAP_VIDEO 路径，
  点右上 Run Script，然后：
    1. 鼠标进 3D 视口 -> 按 Z 选 Rendered
    2. 按 Numpad 0 进入 atk_cam 相机视角
    3. 右上角视口选项里 Compositor 选 Camera（脚本会自动尝试设置）
    4. 播放时间线 / 拖帧条：黄=对上，纯红=视频有你没跟上，纯绿=你滞留
  K 帧照常：骨骼控制器仍显示在 compositor 结果之上，直接摆姿势。

用法 B：文件末尾 mocap_setup() / mocap_restore() 可被 MCP/控制台直接调用。

通道数学（与离线 numpy 版同构）：
  R = 视频亮度 x 视频掩码（make_red_ref.py 已预处理，含掩码外 0.25 淡化）
  G = 模型亮度 x (alpha x 0.75 + 0.25)   <- 掩码外同样 0.25 淡化
  B = 0
两个 Value 节点 R_GAIN / G_GAIN 可在节点面板里实时拉亮度。
"""
import bpy

# ============ 用户设置 ============
MOCAP_VIDEO = r"H:\claude_workspace\3d_hub\projects\动作捕捉\red_ref_00016.mp4"
FRAME_OFFSET = 0          # 视频帧相对场景帧的偏移（场景帧 = 视频帧 + 偏移）
R_GAIN = 1.0              # 红通道增益（觉得视频暗就拉高）
G_GAIN = 1.0              # 绿通道增益（狼毛色暗导致绿看不清就拉高）
# =================================

TAG = "MOCAPRG_"
BACKUP_KEY = "_mocap_rg_backup"


def _make_node(tree, candidates, x, y, label=None):
    """按候选名依次尝试建节点（兼容 5.x 新旧节点名）"""
    for t in candidates:
        try:
            n = tree.nodes.new(t)
            n.location = (x, y)
            if label:
                n.label = label
            return n
        except RuntimeError:
            continue
    raise RuntimeError(f"建不了节点: {candidates}")


def _set_viewport_compositor(mode="CAMERA"):
    for wm in bpy.data.window_managers:
        for win in wm.windows:
            for area in win.screen.areas:
                if area.type == 'VIEW_3D':
                    for space in area.spaces:
                        if space.type == 'VIEW_3D':
                            try:
                                space.shading.use_compositor = mode
                                print(f"  视口 [{area.x+area.width//2}] use_compositor={mode}")
                            except Exception as e:
                                print("  视口设置失败(可手动选):", e)


def mocap_setup(video_path=None, frame_offset=None, r_gain=None, g_gain=None):
    sc = bpy.context.scene
    video_path = video_path or MOCAP_VIDEO
    frame_offset = FRAME_OFFSET if frame_offset is None else frame_offset
    r_gain = R_GAIN if r_gain is None else r_gain
    g_gain = G_GAIN if g_gain is None else g_gain

    import json
    # ---- 备份（幂等：重复 setup 先恢复再重来） ----
    if BACKUP_KEY in sc:
        mocap_restore(quiet=True)
    backup = {"film_transparent": sc.render.film_transparent,
              "use_nodes": sc.use_nodes,
              "hidden_meshes": []}
    sc[BACKUP_KEY] = json.dumps(backup)

    # ---- 1. 视口里已隐藏、但渲染仍会出现的 mesh -> 渲染也隐藏（如 Mesh_0 高模） ----
    for o in bpy.data.objects:
        if o.type == 'MESH' and o.hide_get() and not o.hide_render:
            o.hide_render = True
            backup["hidden_meshes"].append(o.name)
            print(f"  渲染隐藏: {o.name}")
    sc[BACKUP_KEY] = json.dumps(backup)

    # ---- 2. 透明底：alpha 通道即狼掩码 ----
    sc.render.film_transparent = True

    # ---- 3. 合成器节点树（Blender 5.1: scene.compositing_node_group）----
    sc.use_nodes = True
    tree = getattr(sc, "compositing_node_group", None) or getattr(sc, "node_tree", None)
    owned_tree = False
    if tree is None:
        tree = bpy.data.node_groups.new("MOCAP_RG_Tree", 'CompositorNodeTree')
        sc.compositing_node_group = tree
        owned_tree = True
    backup["owned_tree"] = owned_tree
    sc[BACKUP_KEY] = json.dumps(backup)
    for n in [n for n in tree.nodes if n.name.startswith(TAG)]:
        tree.nodes.remove(n)
    if len([n for n in tree.nodes]) > 0:
        print(f"  注意: 原合成树有 {len(tree.nodes)} 个其他节点，已保留未动")

    rl = _make_node(tree, ['CompositorNodeRLayers'], -900, 0, "狼(渲染层)")
    img_node = _make_node(tree, ['CompositorNodeImage'], -900, -350, "H3红视频")

    # 优先用 PNG 序列目录（合成器里帧跟随最可靠）；给 mp4 也能用但可能不随帧刷新
    from pathlib import Path as _P
    vp = _P(video_path)
    load_path = video_path
    if vp.is_dir():
        seq = sorted(vp.glob("*.png"))
        if not seq:
            raise RuntimeError(f"序列目录没有 png: {video_path}")
        load_path = str(seq[0])
        print(f"  使用序列: {seq[0].name} .. {seq[-1].name} 共{len(seq)}张")
    elif vp.with_name(vp.stem + "_frames").is_dir():
        seq = sorted(vp.with_name(vp.stem + "_frames").glob("*.png"))
        if seq:
            load_path = str(seq[0])
            print(f"  使用序列目录: {vp.stem}_frames/ 共{len(seq)}张")

    vid = None
    for im in bpy.data.images:
        if im.filepath and load_path.lower() in bpy.path.abspath(im.filepath).lower():
            vid = im
            break
    if vid is None:
        vid = bpy.data.images.load(load_path)
    if vid.source != 'SEQUENCE':
        vid.source = 'SEQUENCE'   # 识别为序列，自动扫描目录帧数
    img_node.image = vid
    try:
        img_node.use_auto_refresh = True   # 关键：序列帧跟随场景帧刷新
        img_node.use_cyclic = False
        img_node.frame_offset = frame_offset
        n_frames = vid.frame_duration or 1
        if load_path.lower().endswith('.png'):
            n_frames = len(sorted(_P(load_path).parent.glob('*.png')))
        img_node.frame_duration = n_frames   # 关键：显式告知序列长度，否则渲染钳在第1帧
        print(f"  序列帧数已设: {img_node.frame_duration}")
    except Exception as e:
        print("  帧刷新设置异常:", e)

    # R 侧：视频 Red 通道 x R_GAIN（G/B 预处理时已为 0）
    sep_v = _make_node(tree, ['CompositorNodeSeparateColor'], -650, -350, "视频.R")
    m_r = _make_node(tree, ['ShaderNodeMath'], -450, -350, "R x gain(调视频亮度)")
    m_r.operation = 'MULTIPLY'
    m_r.inputs[1].default_value = r_gain

    # G 侧：狼 luma = (R+G+B)/3，再 x (alpha x 0.75 + 0.25) x G_GAIN
    sep_m = _make_node(tree, ['CompositorNodeSeparateColor'], -1150, 200, "狼RGB")
    m_add1 = _make_node(tree, ['ShaderNodeMath'], -950, 250, "R+G")
    m_add1.operation = 'ADD'
    m_add2 = _make_node(tree, ['ShaderNodeMath'], -800, 250, "+B")
    m_add2.operation = 'ADD'
    m_luma = _make_node(tree, ['ShaderNodeMath'], -650, 250, "/3=亮度")
    m_luma.operation = 'MULTIPLY'
    m_luma.inputs[1].default_value = 1.0 / 3.0
    m_alfa = _make_node(tree, ['ShaderNodeMath'], -650, 460, "alpha*0.75+0.25")
    m_alfa.operation = 'MULTIPLY_ADD'
    m_alfa.inputs[1].default_value = 0.75
    m_alfa.inputs[2].default_value = 0.25
    m_g = _make_node(tree, ['ShaderNodeMath'], -450, 300, "亮度x alpha淡")
    m_g.operation = 'MULTIPLY'
    m_ggain = _make_node(tree, ['ShaderNodeMath'], -300, 300, "G x gain(调狼亮度)")
    m_ggain.operation = 'MULTIPLY'
    m_ggain.inputs[1].default_value = g_gain

    comb = _make_node(tree, ['CompositorNodeCombineColor'], -100, 0, "R|G|B")
    comb.inputs['Blue'].default_value = 0.0
    comb.inputs['Alpha'].default_value = 1.0

    out_view = _make_node(tree, ['CompositorNodeViewer'], 150, -180, "Viewer")
    gout = _make_node(tree, ['NodeGroupOutput'], 350, 0, "对位输出")
    if not any(s.identifier == 'Image' for s in tree.interface.items_tree):
        tree.interface.new_socket('Image', in_out='OUTPUT',
                                  socket_type='NodeSocketColor')

    links = tree.links
    links.new(img_node.outputs['Image'], sep_v.inputs['Image'])
    links.new(sep_v.outputs['Red'], m_r.inputs[0])

    links.new(rl.outputs['Image'], sep_m.inputs['Image'])
    links.new(sep_m.outputs['Red'], m_add1.inputs[0])
    links.new(sep_m.outputs['Green'], m_add1.inputs[1])
    links.new(m_add1.outputs[0], m_add2.inputs[0])
    links.new(sep_m.outputs['Blue'], m_add2.inputs[1])
    links.new(m_add2.outputs[0], m_luma.inputs[0])
    links.new(rl.outputs['Alpha'], m_alfa.inputs[0])
    links.new(m_luma.outputs[0], m_g.inputs[0])
    links.new(m_alfa.outputs[0], m_g.inputs[1])
    links.new(m_g.outputs[0], m_ggain.inputs[0])

    links.new(m_r.outputs[0], comb.inputs['Red'])
    links.new(m_ggain.outputs[0], comb.inputs['Green'])
    links.new(comb.outputs['Image'], out_view.inputs['Image'])
    links.new(comb.outputs['Image'], gout.inputs['Image'])

    for n in (rl, img_node, sep_v, m_r, sep_m, m_add1, m_add2, m_luma,
              m_alfa, m_g, m_ggain, comb, out_view, gout):
        n.name = TAG + n.label.replace(" ", "").replace("(", "").replace(")", "")

    # ---- 4. 视口启用合成器预览（相机视图下生效） ----
    _set_viewport_compositor('CAMERA')

    print("=== 红绿对位已搭建 ===")
    print("视口: Z->Rendered, Numpad0 进 atk_cam, 播放时间线看效果")
    print(f"视频: {vid.name}  帧数={vid.frame_duration}  偏移={frame_offset}")
    print(f"场景帧范围: {sc.frame_start}-{sc.frame_end} (视频 {vid.frame_duration} 帧, 超出会停最后一帧)")
    return {"FINISHED"}


def mocap_restore(quiet=False):
    sc = bpy.context.scene
    import json
    if BACKUP_KEY not in sc:
        if not quiet:
            print("没有可还原的备份")
        return {'CANCELLED'}
    backup = json.loads(sc[BACKUP_KEY])

    # 删我们的节点（若整棵树是我们建的，连树一起删）
    tree = getattr(sc, "compositing_node_group", None) or getattr(sc, "node_tree", None)
    if tree:
        if backup.get("owned_tree"):
            try:
                sc.compositing_node_group = None
            except Exception:
                pass
            if tree.name in bpy.data.node_groups:
                bpy.data.node_groups.remove(tree)
        else:
            for n in [n for n in tree.nodes if n.name.startswith(TAG)]:
                tree.nodes.remove(n)
        sc.use_nodes = backup["use_nodes"]

    sc.render.film_transparent = backup["film_transparent"]
    for name in backup.get("hidden_meshes", []):
        o = bpy.data.objects.get(name)
        if o:
            o.hide_render = False
    del sc[BACKUP_KEY]
    _set_viewport_compositor('DISABLED')
    if not quiet:
        print("=== 已还原（合成节点/透明底/渲染隐藏 全部恢复） ===")
    return {'FINISHED'}


if __name__ == "__main__":
    mocap_setup()
