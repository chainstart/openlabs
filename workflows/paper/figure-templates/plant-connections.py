"""Matched PV and two-hour storage layouts in the five-minute NEM replay."""
from object_scene import Scene, ORANGE

s = Scene(175)
for offset, shared in ((0,False),(365,True)):
    def at(x,y):
        return (offset+x,y)
    s.label(*at(8,16),"b   Shared connection" if shared else "a   Separate connections",15,"start",True)
    s.object("energy/pv.svg",*at(52,54),80)
    s.object("energy/battery.svg",*at(52,125),82)
    s.object("energy/tower.svg",*at(307,92),86)
    s.label(*at(52,92),"Solar PV")
    s.label(*at(54,163),"2 h battery")
    s.label(*at(308,139),"Grid")
    if shared:
        s.flow([at(94,55),at(142,55)])
        s.line([at(142,55),at(163,55),at(163,125)],"#0072B2",width=2)
        s.flow([at(94,125),at(163,125)],both=True)
        s.line([at(163,88),at(178,88)],"#0072B2",width=2)
        s.flow([at(178,88),at(268,88)],both=True)
        s.limit(*at(217,88),"Joint limit")
        s.object("energy/meter.svg",*at(217,123),42)
        s.line([at(217,97),at(217,108)])
        s.flow([at(87,66),at(106,80),at(106,99),at(86,113)],signal=True,color=ORANGE)
    else:
        for y,delta,label in ((55,-8,"PV limit"),(125,8,"Battery limit")):
            s.flow([at(94,y),at(217,y),at(269,89+delta)],both=y==125)
            s.limit(*at(165,y),label)
s.line([(359,4),(359,169)],"#E4E4E4")
s.save()
