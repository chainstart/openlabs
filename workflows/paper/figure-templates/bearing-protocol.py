"""Illustrative specimen-level split before signal segmentation."""
from object_scene import Scene
s = Scene(195)
s.label(14,22,"Assign whole bearings before cutting windows",16,"start",True)
s.object("reliability/bench.svg",70,102,127)
s.flow([(132,103),(164,103),(164,66),(205,66)])
s.flow([(164,103),(164,140),(205,140)])
for y,label,count in [(66,"Training",4),(140,"Held out",2)]:
    for i in range(count):
        s.object("reliability/bearing.svg",228+36*i,y,42)
    s.label(401,y+4,f"{label} · {count} units",bold=True)
    s.flow([(477,y),(514,y)],signal=True)
    for i in range(5):
        x=526+i*30
        s.line([(x,y+10),(x,y-10),(x+25,y-10),(x+25,y+10),(x,y+10)])
    s.label(599,y+32,"1 s windows within each unit")
s.save()
