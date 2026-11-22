"""Uniform disk, central transit; geometric flux loss at full overlap."""
from object_scene import Scene
s = Scene(208)
s.label(12,22,"a   Projected stellar disk",16,"start",True)
s.label(358,22,"b   Integrated stellar flux",16,"start",True)
for x,offset in [(61,-42),(165,0),(269,42)]:
    s.object("astronomy/star.svg",x,88,104)
    s.parts.append(f'<circle cx="{x+offset}" cy="88" r="5.82" fill="#222222"/>')
for x,label in [(61,"Before"),(165,"Mid-transit"),(269,"After")]:
    s.label(x,149,label)
s.line([(392,48),(392,147),(697,147)])
s.line([(394,71),(461,71),(477,116),(601,116),(617,71),(695,71)],"#0072B2",width=2.7)
s.label(388,75,"1.00",anchor="end")
s.label(388,120,"0.96",anchor="end")
s.label(543,169,"Time →")
s.label(358,198,"Uniform stellar disk · radius ratio 0.20 · full-overlap flux loss = 0.20² = 4%")
s.save()
