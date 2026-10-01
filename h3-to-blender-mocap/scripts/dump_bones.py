# -*- coding: utf-8 -*-
"""dump rig 控制骨骼地图（供 AI K 帧防呆用）"""
import bpy

rig = bpy.data.objects.get("rig")
if not rig:
    print("找不到 rig")
else:
    pbs = rig.pose.bones
    print(f"rig: {rig.name}  pose bones 总数={len(pbs)}")
    # Rigify 控制骨 = 名字不带 DEF-/ORG-/MCH- 前缀（控制在主层）
    ctrls = [b for b in pbs if not b.name.startswith(('DEF-', 'ORG-', 'MCH-', 'VIS-'))]
    print(f"控制骨骼数={len(ctrls)}")
    print("\n=== 控制骨骼清单（名字 | 父级 | 旋转模式 | 自定义形状） ===")
    for b in ctrls:
        shape = b.custom_shape.name if b.custom_shape else '-'
        parent = b.parent.name if b.parent else '-'
        print(f"  {b.name} | {parent} | {b.rotation_mode} | {shape}")

    print("\n=== 关键组采样（IK/FK 判断） ===")
    ik = [b.name for b in ctrls if 'ik' in b.name.lower()]
    fk = [b.name for b in ctrls if 'fk' in b.name.lower()]
    print(f"IK 控制({len(ik)}): {sorted(ik)}")
    print(f"FK 控制({len(fk)}): {sorted(fk)[:30]}")

    print("\n=== 约束（看主控制器被什么驱动） ===")
    for b in ctrls[:60]:
        for c in b.constraints:
            if c.type in ('IK', 'COPY_ROTATION', 'COPY_LOCATION', 'DAMPED_TRACK', 'TRACK_TO'):
                print(f"  {b.name}: {c.type} -> {getattr(c, 'subtarget', '')}")
