#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AgentProxyHub 专属应用图标生成器
输出高保真、暗黑极客美学的多分辨率 Windows ICO 与高清 PNG
"""

import os
import math
from PIL import Image, ImageDraw, ImageFilter

def create_agentproxyhub_icon(size=512):
    # 创建透明背景画板
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # 1. 绘制外部深黑圆角矩阵底座 (Dark Hexagon / Shield)
    center = size / 2
    r_outer = size * 0.44

    # 计算平滑六边形顶点
    points = []
    for i in range(6):
        angle = math.radians(60 * i - 30)
        x = center + r_outer * math.cos(angle)
        y = center + r_outer * math.sin(angle)
        points.append((x, y))

    # 阴影层
    shadow_img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    s_draw = ImageDraw.Draw(shadow_img)
    s_draw.polygon(points, fill=(0, 0, 0, 180))
    shadow_img = shadow_img.filter(ImageFilter.GaussianBlur(radius=16))
    img.paste(shadow_img, (0, 12), shadow_img)

    # 主底座多边形 (深邃石墨黑 + 发丝线边框)
    draw.polygon(points, fill=(20, 22, 28, 255), outline=(55, 65, 85, 255))

    # 内缩一层装饰线
    r_inner_border = r_outer * 0.92
    inner_pts = []
    for i in range(6):
        angle = math.radians(60 * i - 30)
        x = center + r_inner_border * math.cos(angle)
        y = center + r_inner_border * math.sin(angle)
        inner_pts.append((x, y))
    draw.polygon(inner_pts, outline=(36, 44, 58, 255))

    # 2. 绘制多端口总线轨迹 (Bus Traces)
    # 从中心向 4 个方向引出科技感总线
    line_color = (60, 130, 246, 200) # 科技蓝
    glow_color = (96, 165, 250, 255)
    
    # 4条主要端口线路 (上、下、左、右)
    offset_dist = size * 0.30
    ports = [
        (center, center - offset_dist), # 上
        (center, center + offset_dist), # 下
        (center - offset_dist, center), # 左
        (center + offset_dist, center)  # 右
    ]

    for px, py in ports:
        draw.line([(center, center), (px, py)], fill=line_color, width=int(size * 0.024))
        # 端口节点端点圆环
        draw.ellipse([px - 14, py - 14, px + 14, py + 14], fill=(24, 30, 42, 255), outline=glow_color, width=3)
        draw.ellipse([px - 6, py - 6, px + 6, py + 6], fill=(59, 130, 246, 255))

    # 3. 绘制斜向 4 个次级节点 (Claude 紫 / OpenAI 绿)
    sub_dist = size * 0.24
    sub_ports = [
        ((center - sub_dist * 0.7, center - sub_dist * 0.7), (192, 132, 252, 255)), # 左上: Claude 紫
        ((center + sub_dist * 0.7, center - sub_dist * 0.7), (74, 222, 128, 255)),  # 右上: OpenAI 绿
        ((center - sub_dist * 0.7, center + sub_dist * 0.7), (96, 165, 250, 255)),  # 左下: Blue
        ((center + sub_dist * 0.7, center + sub_dist * 0.7), (251, 191, 36, 255))   # 右下: Amber
    ]
    for (spx, spy), col in sub_ports:
        draw.line([(center, center), (spx, spy)], fill=(col[0], col[1], col[2], 120), width=int(size * 0.016))
        draw.ellipse([spx - 8, spy - 8, spx + 8, spy + 8], fill=col)

    # 4. 绘制中心中枢内核 (Hub Core)
    core_r = size * 0.12
    # 外层发光
    draw.ellipse([center - core_r, center - core_r, center + core_r, center + core_r],
                 fill=(22, 27, 38, 255), outline=(96, 165, 250, 255), width=int(size * 0.018))
    
    # 内核中央发光宝石/芯片
    inner_r = core_r * 0.55
    draw.ellipse([center - inner_r, center - inner_r, center + inner_r, center + inner_r],
                 fill=(59, 130, 246, 255))
    
    # 芯片微型高光
    hi_r = inner_r * 0.35
    draw.ellipse([center - hi_r - 2, center - hi_r - 3, center + hi_r - 2, center + hi_r - 3],
                 fill=(255, 255, 255, 220))

    return img

def main():
    assets_dir = os.path.dirname(os.path.abspath(__file__))
    png_path = os.path.join(assets_dir, "icon.png")
    ico_path = os.path.join(assets_dir, "app.ico")

    # 生成 512x512 高清原图
    base_img = create_agentproxyhub_icon(512)
    base_img.save(png_path, format="PNG")
    print(f"✓ Saved PNG: {png_path}")

    # 生成多尺寸标准 Windows ICO (256, 128, 64, 48, 32, 24, 16)
    sizes = [(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (24, 24), (16, 16)]
    base_img.save(ico_path, format="ICO", sizes=sizes)
    print(f"✓ Saved ICO: {ico_path} with sizes {sizes}")

if __name__ == "__main__":
    main()
