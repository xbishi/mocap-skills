# -*- coding: utf-8 -*-
"""指骨清理: 安全检查(权重) -> 删除 -> 清理动作曲线 -> 孤儿回收"""
import bpy
import re

rig = bpy.data.objects.get("rig")
wolf = bpy.data.objects.get("狐狼")
arm = rig.data

# 1. 找出所有指骨
finger_names = [b.name for b in arm.bones
                if re.match(r"^(f_|r_)(index|middle|pinky|ring|thumb)", b.name)]
print(f"指骨总数: {len(finger_names)}")
print(" ", finger_names)

# 2. 权重安全检查(狐狼网格顶点组)
weighted = []
vgmap = {g.index: g.name for g in wolf.vertex_groups}
vsum = {n: 0.0 for n in finger_names}
for v in wolf.data.vertices:
    for ge in v.groups:
        gname = vgmap.get(ge.group)
        if gname in vsum:
            vsum[gname] += ge.weight
for n, tot in vsum.items():
    if tot > 0.001:
        weighted.append((n, round(tot, 3)))
print(f"有权重的指骨: {weighted if weighted else '无 ✓ 可安全删除'}")

if weighted:
    raise SystemExit("存在权重绑定, 中止删除(需先处理权重)")

# 3. 删动作里的指骨曲线
removed_fc = 0
for act in bpy.data.actions:
    chans = []
    try:
        chans = list(act.fcurves)
    except AttributeError:
        for layer in act.layers:
            for strip in layer.strips:
                for cb in strip.channelbags:
                    chans.extend(cb.fcurves)
    for fc in list(chans):
        bone = fc.data_path.split('"')[1] if '"' in fc.data_path else None
        if bone in finger_names:
            try:
                if hasattr(act, "fcurves"):
                    act.fcurves.remove(fc)
                else:
                    for layer in act.layers:
                        for strip in layer.strips:
                            for cb in strip.channelbags:
                                if fc in list(cb.fcurves):
                                    cb.fcurves.remove(fc)
                removed_fc += 1
            except Exception:
                pass
print(f"动作中指骨曲线已删: {removed_fc} 条")

# 4. 编辑模式删骨
bpy.context.view_layer.objects.active = rig
bpy.ops.object.mode_set(mode="EDIT")
deleted = 0
for name in finger_names:
    eb = arm.edit_bones.get(name)
    if eb:
        arm.edit_bones.remove(eb)
        deleted += 1
bpy.ops.object.mode_set(mode="OBJECT")
print(f"已删除骨骼: {deleted} 根, 剩余总数 {len(arm.bones)}")

# 5. 清孤儿(widget等)
bpy.data.orphans_purge(do_local_ids=True, do_linked_ids=False, do_recursive=True)
bpy.ops.wm.save_mainfile()
print("已保存")
