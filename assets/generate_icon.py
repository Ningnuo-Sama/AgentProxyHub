#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""原创 APH 切角中枢标识：黑紫、荧光绿、警戒橙；不使用官方徽记。"""
from pathlib import Path
from PIL import Image, ImageDraw


def create_agentproxyhub_icon(size=512):
    scale = 4
    canvas = Image.new('RGBA', (size * scale, size * scale), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    def pts(values):
        return [(int(x * size * scale), int(y * size * scale)) for x, y in values]
    shield = pts([(0.22, 0.08), (0.78, 0.08), (0.92, 0.22), (0.92, 0.78), (0.78, 0.92), (0.22, 0.92), (0.08, 0.78), (0.08, 0.22)])
    draw.polygon(shield, fill='#100C19')
    draw.line(shield + [shield[0]], fill='#996BDA', width=max(1, int(size * scale * 0.045)), joint='curve')
    # Three separated conduits converge on an open hexagonal control core.
    for route in [[(0.18, 0.31), (0.34, 0.31), (0.43, 0.43)], [(0.82, 0.31), (0.66, 0.31), (0.57, 0.43)], [(0.5, 0.82), (0.5, 0.62)]]:
        draw.line(pts(route), fill='#B7FF00', width=max(1, int(size * scale * 0.055)), joint='curve')
    core = pts([(0.5, 0.35), (0.64, 0.43), (0.64, 0.57), (0.5, 0.65), (0.36, 0.57), (0.36, 0.43)])
    draw.polygon(core, fill='#241735')
    draw.line(core + [core[0]], fill='#B7FF00', width=max(1, int(size * scale * 0.035)), joint='curve')
    draw.polygon(pts([(0.73, 0.7), (0.83, 0.7), (0.73, 0.8)]), fill='#FFAA4A')
    return canvas.resize((size, size), Image.Resampling.LANCZOS)


def main():
    directory = Path(__file__).resolve().parent
    image = create_agentproxyhub_icon()
    image.save(directory / 'icon.png', format='PNG')
    sizes = [(s, s) for s in (16, 24, 32, 48, 64, 128, 256)]
    image.save(directory / 'app.ico', format='ICO', sizes=sizes)
    print('Generated original 512px PNG and 7-size Windows ICO.')


if __name__ == '__main__':
    main()
