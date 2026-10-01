# -*- coding: utf-8 -*-
"""标定：IK 脚/躯干控制骨 local 位移 -> 世界方向映射 + right_cam 视图参数"""
import bpy, mathutils

rig = bpy.data.objects.get("rig")
sc = bpy.context.scene

print("=== right_cam 参数 ===")
cam = bpy.data.objects.get("right_cam")
if cam:
    print(f"  loc={tuple(round(v,3) for v in cam.location)}")
    print(f"  rot_euler={tuple(round(v,4) for v in cam.rotation_euler)}")
    print(f"  ortho_scale={cam.data.ortho_scale:.4f}")
    # 相机朝向与世界轴向
    fwd = cam.matrix_world.to_quaternion() @ mathutils.Vector((0, 0, -1))
    right = cam.matrix_world.to_quaternion() @ mathutils.Vector((1, 0, 0))
    up = cam.matrix_world.to_quaternion() @ mathutils.Vector((0, 1, 0))
    print(f"  屏幕右(世界) = {tuple(round(v,3) for v in right)}")
    print(f"  屏幕上(世界) = {tuple(round(v,3) for v in up)}")
    print(f"  相机前向(世界) = {tuple(round(v,3) for v in fwd)}")

print("\n=== 控制骨 local->世界位移标定 ===")
targets = ["front_foot_ik.L", "front_foot_ik.R", "foot_ik.L", "foot_ik.R", "torso", "head"]
# 保存原 location
orig = {}
for n in targets:
    b = rig.pose.bones.get(n)
    if b:
        orig[n] = b.location.copy()
for n in targets:
    b = rig.pose.bones.get(n)
    if not b:
        print(f"  {n}: 不存在!"); continue
    w0 = rig.matrix_world @ b.head
    line = f"  {n}: head世界=({w0.x:.3f},{w0.y:.3f},{w0.z:.3f}) "
    for axis in range(3):
        loc = orig[n].copy()
        loc[axis] += 0.1
        b.location = loc
        bpy.context.view_layer.update()
        w1 = rig.matrix_world @ b.head
        d = w1 - w0
        line += f" | loc{['X','Y','Z'][axis]}+0.1 -> 世界Δ({d.x:+.2f},{d.y:+.2f},{d.z:+.2f})"
        b.location = orig[n].copy()
    bpy.context.view_layer.update()
    print(line)

# 恢复
for n, v in orig.items():
    rig.pose.bones[n].location = v
bpy.context.view_layer.update()
print("\n已还原所有测试位移")
