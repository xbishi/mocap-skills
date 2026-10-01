# -*- coding: utf-8 -*-
"""红绿叠加参考源切换: walk <-> run
用法(经 blender_exec 或 Blender 内): 切换后合成器红通道即显示对应参考
  switch_overlay("walk")  # red_ref_00016_frames, offset 8
  switch_overlay("run")   # red_ref_run20_frames, offset 23
"""
import bpy

BASE = r"H:\claude_workspace\3d_hub\projects\动作捕捉"
PRESETS = {
    "walk": {"seq_dir": BASE + r"\red_ref_00016_frames", "offset": 8,
             "action": "walk", "range": (1, 64)},
    "run":  {"seq_dir": BASE + r"\red_ref_run20_frames", "offset": 19,
             "action": "run", "range": (1, 64)},
}


def switch_overlay(mode: str, switch_action: bool = True):
    cfg = PRESETS[mode]
    sc = bpy.context.scene
    tree = getattr(sc, "compositing_node_group", None)
    assert tree, "场景里没有合成器节点树(先跑 setup_overlay)"
    node = next(n for n in tree.nodes if n.name.startswith("MOCAPRG_H3红视频"))

    # 换图源(优先 PNG 序列目录的第一张)
    from pathlib import Path
    seq = sorted(Path(cfg["seq_dir"]).glob("*.png"))
    assert seq, f"序列目录为空: {cfg['seq_dir']}"
    path = str(seq[0])
    img = None
    for im in bpy.data.images:
        if im.filepath and path.lower() in bpy.path.abspath(im.filepath).lower():
            img = im
            break
    if img is None:
        img = bpy.data.images.load(path)
    img.name = f"MOCAP_RED_{mode}"
    node.image = img
    if img.source != "SEQUENCE":
        img.source = "SEQUENCE"
    node.use_auto_refresh = True
    node.frame_duration = len(seq)
    node.frame_offset = cfg["offset"]     # 用户约定的帧映射
    print(f"红参考 -> {mode}: {len(seq)} 帧, offset={cfg['offset']}")

    # 可选: 同步切换 rig 动作与场景范围
    if switch_action:
        rig = bpy.data.objects.get("rig")
        act = bpy.data.actions.get(cfg["action"])
        if act:
            rig.animation_data.action = act
            sc.frame_start, sc.frame_end = cfg["range"]
            sc.frame_set(cfg["range"][0])
            print(f"rig 动作 -> {cfg['action']}, 场景范围 {cfg['range'][0]}-{cfg['range'][1]}")


if __name__ == "__main__":
    import sys
    mode = "run"
    for a in sys.argv:
        if a in PRESETS:
            mode = a
    switch_overlay(mode)
