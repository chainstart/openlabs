"""Compose equipment, paths and labels in a 720-unit print-width coordinate system."""
import math
import os
from pathlib import Path
from xml.sax.saxutils import escape
import xml.etree.ElementTree as ET

from openlabs_fig import DOUBLE_COLUMN_MM, PALETTE, find_asset
ET.register_namespace("", "http://www.w3.org/2000/svg")

INK = PALETTE["ink"]
BLUE = PALETTE["blue"]
ORANGE = PALETTE["vermilion"]


class Scene:
    def __init__(self, height):
        self.height = height
        self.parts = []

    def object(self, asset, x, y, width):
        """Place an object centred on the given alignment point, preserving aspect."""
        root = ET.parse(find_asset(asset)).getroot()
        a, b, w, h = map(float, root.attrib["viewBox"].split())
        scale = width / w
        body = "".join(ET.tostring(child, encoding="unicode") for child in root)
        self.parts.append(f'<g transform="translate({x-width/2} {y-h*scale/2}) scale({scale}) translate({-a} {-b})">{body}</g>')

    def label(self, x, y, value, size=12, anchor="middle", bold=False):
        weight = "bold" if bold else "normal"
        self.parts.append(f'<text x="{x}" y="{y}" text-anchor="{anchor}" font-family="Helvetica" font-size="{size}" font-weight="{weight}" fill="{INK}">{escape(value)}</text>')

    def line(self, points, color=INK, dashed=False, width=1.6):
        coords = " ".join(f"{x},{y}" for x, y in points)
        dash = ' stroke-dasharray="5 3"' if dashed else ""
        self.parts.append(f'<polyline points="{coords}" fill="none" stroke="{color}" stroke-width="{width}"{dash}/>')

    def flow(self, points, both=False, signal=False, color=BLUE):
        self.line(points, color, signal, 2)
        ends = [(points[-2], points[-1])]
        if both:
            ends.append((points[1], points[0]))
        for (x,y),(u,v) in ends:
            angle = math.atan2(v-y,u-x)
            wings = [(u-7*math.cos(angle+t), v-7*math.sin(angle+t)) for t in (-.48,.48)]
            self.line([wings[0],(u,v),wings[1]],color,width=2)

    def limit(self, x, y, label):
        for dx in (-2,2):
            self.line([(x+dx,y-7),(x+dx,y+7)],ORANGE,width=2)
        self.label(x,y-12,label)

    def leader(self, points, label):
        self.line(points)
        self.label(*points[-1],label,anchor="start")

    def save(self):
        width = DOUBLE_COLUMN_MM
        svg = f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}mm" height="{width*self.height/720}mm" viewBox="0 0 720 {self.height}">' + "".join(self.parts) + '</svg>'
        if os.environ.get("FIG_SVG"):
            Path(os.environ["FIG_SVG"]).write_text(svg)
        else:
            import fitz
            with fitz.open(stream=svg.encode(),filetype="svg") as doc:
                Path(os.environ["FIG_OUT"]).write_bytes(doc.convert_to_pdf())
