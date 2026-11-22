"""Illustrative AC-bus balance over a single five-minute interval."""
from object_scene import Scene

s = Scene(210)
s.label(12,21,"a   Available solar power",16,"start",True)
s.label(384,21,"b   Shared point of connection",16,"start",True)
for name,x,y,w in [("energy/pv.svg",65,82,116),("energy/inverter.svg",221,82,100),
                   ("energy/meter.svg",495,82,89),("energy/tower.svg",651,82,119),
                   ("energy/battery.svg",344,161,101)]:
    s.object(name,x,y,w)
s.flow([(128,82),(186,82)])
s.flow([(258,82),(465,82)])
s.flow([(525,82),(607,82)])
s.flow([(344,82),(344,127)])
s.limit(428,82,"5 MW cap")
for x,value in [(64,"PV array"),(215,"Inverter"),(498,"Meter"),(652,"Grid")]:
    s.label(x,139,value)
s.label(291,74,"7 MW AC")
s.label(565,73,"5 MW")
s.label(355,112,"2 MW charge",anchor="start")
s.label(344,207,"2 MW / 4 MWh storage")
s.save()
