# -*- coding: utf-8 -*-
"""红参考 -> 抠黑底变透明 -> 挂相机前景(display_depth=FRONT)
红狼浮在模型上方, 半透明对比; 视口合成器切 DISABLED(避免红绿模式干扰)
"""
import bpy
import subprocess
from pathlib import Path

BASE = Path(r"H:\claude_workspace\3d_hub\projects\动作捕捉")
SRC = BASE / "red_ref_run20_frames"
DST = BASE / "red_ref_run20_alpha"
DST.mkdir(exist_ok=True)

# 1. 全部帧: 黑底抠透明(lumakey 只抠纯黑, 深色毛发保留)
for f in sorted(SRC.glob("*.png")):
    out = DST / f.name
    if not out.exists():
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(f),
                        "-vf", "lumakey=threshold=0:tolerance=0.05",
                        "-pix_fmt", "rgba", str(out)], check=True)
n = len(list(DST.glob("*.png")))
print(f"透明帧: {n} 张")

# 2. 挂到 right_cam 前景
sc = bpy.context.scene
cam = bpy.data.objects.get("right_cam")
img = None
for im in bpy.data.images:
    if im.filepath and str(DST / "o_0001.png").lower() in bpy.path.abspath(im.filepath).lower():
        img = im
        break
if img is None:
    img = bpy.data.images.load(str(DST / "o_0001.png"))
img.name = "RED_GHOST_run20"
if img.source != "SEQUENCE":
    img.source = "SEQUENCE"

bg = None
for b in cam.data.background_images:
    if b.image and b.image.name.startswith("RED_GHOST"):
        bg = b
        break
if bg is None:
    bg = cam.data.background_images.new()
bg.image = img
bg.show_background_image = True
bg.display_depth = "FRONT"        # 关键: 画在模型前面
bg.alpha = 1.0
bg.frame_method = "FIT"

# 帧对齐: 场景1 = 视频14 (序列偏移13)
try:
    iu = bg.image_user
    iu.use_auto_refresh = True
    iu.frame_duration = n
    iu.frame_offset = 13
    print(f"序列对齐: offset={iu.frame_offset} duration={iu.frame_duration}")
except Exception as e:
    print("对齐设置跳过:", e)

# 3. 相机视口合成器切 DISABLED(红绿合成模式与前景红狼叠加会互相干扰)
for wm in bpy.data.window_managers:
    for win in wm.windows:
        for area in win.screen.areas:
            if area.type == "VIEW_3D":
                for sp in area.spaces:
                    if sp.type == "VIEW_3D" and sp.region_3d.view_perspective == "CAMERA":
                        sp.shading.use_compositor = "DISABLED"
                        print("相机视口合成器 -> DISABLED")

bpy.ops.wm.save_mainfile()
print("完成: 红狼前景已挂, 视口合成器已关(红绿合成树仍保留在文件里, 随时可切回)")
