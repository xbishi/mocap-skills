# -*- coding: utf-8 -*-
"""干净底座一键初始化: 指骨清理 + IK_Stretch关 + 合成器/背景复位 + 显示复位"""
import bpy
import re

sc = bpy.context.scene
rig = bpy.data.objects.get("rig")
wolf = bpy.data.objects.get("狐狼")
arm = rig.data
cam = bpy.data.objects.get("right_cam")

# 1. 指骨删除(权重检查)
fingers = [b.name for b in arm.bones
           if re.match(r"^(f_|r_)(index|middle|pinky|ring|thumb)", b.name)]
print(f"指骨总数: {len(fingers)}")
weighted = []
if wolf:
    vgmap = {g.index: g.name for g in wolf.vertex_groups}
    vsum = {n: 0.0 for n in fingers}
    for v in wolf.data.vertices:
        for ge in v.groups:
            gn = vgmap.get(ge.group)
            if gn in vsum:
                vsum[gn] += ge.weight
    weighted = [(n, t) for n, t in vsum.items() if t > 0.001]
if weighted:
    print(f"⚠️ 指骨有权重, 跳过删除: {weighted}")
else:
    bpy.context.view_layer.objects.active = rig
    bpy.ops.object.mode_set(mode="EDIT")
    for n in fingers:
        eb = arm.edit_bones.get(n)
        if eb:
            arm.edit_bones.remove(eb)
    bpy.ops.object.mode_set(mode="OBJECT")
    print(f"指骨已删: {len(fingers)} 根, 剩余 {len(arm.bones)}")

# 2. IK_Stretch 关(四腿)
for n in ("thigh_parent.L", "thigh_parent.R",
          "front_thigh_parent.L", "front_thigh_parent.R"):
    b = rig.pose.bones.get(n)
    if b and "IK_Stretch" in b:
        b["IK_Stretch"] = 0.0
print("IK_Stretch 四腿 -> 0")

# 3. 合成器复位: 删除红绿树, use_nodes 关
tree = getattr(sc, "compositing_node_group", None)
if tree:
    sc.compositing_node_group = None
    bpy.data.node_groups.remove(tree)
sc.use_nodes = False
print("合成器树已移除")

# 4. 背景图全清
for b in list(cam.data.background_images):
    cam.data.background_images.remove(b)
print("相机背景图已清空")

# 5. 显示复位(原始状态)
sc.view_settings.view_transform = "AgX"
sc.view_settings.look = "None"
sc.render.film_transparent = False
sc.render.use_compositing = False

# 6. 姿势归零 + 帧范围
for b in rig.pose.bones:
    b.location = (0, 0, 0)
    if b.rotation_mode == "QUATERNION":
        b.rotation_quaternion = (1, 0, 0, 0)
    else:
        b.rotation_euler = (0, 0, 0)
sc.frame_start, sc.frame_end = 1, 64
sc.frame_set(1)

# 7. 清孤儿
bpy.data.orphans_purge(do_local_ids=True, do_linked_ids=False, do_recursive=True)
bpy.ops.wm.save_mainfile()
print("=== 初始化完成并保存 ===")
