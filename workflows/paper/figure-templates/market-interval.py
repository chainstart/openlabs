"""Worked constant-price settlement interval with metered export."""
from object_scene import Scene

s = Scene(178)
s.label(14,20,"Worked settlement interval",16,"start",True)
for asset,x,title in [("energy/meter.svg",73,"Metered export"),("energy/market.svg",644,"Settlement")]:
    s.object(asset,x,88,110)
    s.label(x,154,title,bold=True)
s.flow([(125,88),(589,88)])
for x,t in [(191,"12:00"),(505,"12:05")]:
    s.line([(x,74),(x,102)])
    s.label(x,121,t)
s.label(348,73,"6 MW for 5 min = 0.50 MWh")
s.label(348,149,"At $80/MWh, interval revenue = $40")
s.save()
