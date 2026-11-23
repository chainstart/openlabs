/* openlabs-fig.js -- draws the .ol-flow connectors of an HTML schematic figure.
 *
 * <i class="ol-flow energy" data-from="pv" data-to="bus" data-value="4.2" data-label="4.2 MW"></i>
 *
 *   data-from / data-to    element ids (any element: card, group, icon)
 *   data-from-side / -to-side  left|right|top|bottom (default: chosen from the positions)
 *   data-from-at / -to-at  where on that side, 0..1 (default 0.5)
 *   data-route             straight | hvh | vhv | hv | vh (default hvh for left/right, vhv for top/bottom)
 *   data-mid               0..1, where the middle leg of hvh/vhv sits (default 0.5)
 *   data-value             mapped linearly to stroke width: figure data-flow-max (value of the
 *                          widest line, default the largest value) -> data-flow-width (pt, default 3.6);
 *                          lines never go below 0.7 pt. Without a value: 0.9 pt.
 *   data-label             text placed beside the middle leg; data-label-side above|below|left|right
 *   data-both="1"          heads at both ends; data-head="0" no head
 *   class                  energy | data | signal | material | control (colour; control is dashed)
 * The build waits for fonts, then this script runs before the page is printed.
 */
(function () {
  const PX = 4 / 3; // px per pt
  const NS = "http://www.w3.org/2000/svg";

  function sideOf(a, b) {
    const dx = (b.left + b.right) / 2 - (a.left + a.right) / 2;
    const dy = (b.top + b.bottom) / 2 - (a.top + a.bottom) / 2;
    const overlapX = Math.min(a.right, b.right) - Math.max(a.left, b.left);
    if (overlapX > 0.4 * Math.min(a.width, b.width) || Math.abs(dy) > Math.abs(dx) * 1.4) {
      return dy > 0 ? ["bottom", "top"] : ["top", "bottom"];
    }
    return dx > 0 ? ["right", "left"] : ["left", "right"];
  }

  function anchor(r, side, at) {
    switch (side) {
      case "left": return [r.left, r.top + r.height * at];
      case "right": return [r.right, r.top + r.height * at];
      case "top": return [r.left + r.width * at, r.top];
      default: return [r.left + r.width * at, r.bottom];
    }
  }

  function route(p, q, kind, mid) {
    const [x0, y0] = p, [x1, y1] = q;
    if (kind === "straight") return [p, q];
    if (kind === "hv") return [p, [x1, y0], q];
    if (kind === "vh") return [p, [x0, y1], q];
    if (kind === "vhv") { const ym = y0 + (y1 - y0) * mid; return [p, [x0, ym], [x1, ym], q]; }
    const xm = x0 + (x1 - x0) * mid; return [p, [xm, y0], [xm, y1], q];
  }

  function simplify(points) {
    const out = [points[0]];
    for (let i = 1; i < points.length; i++) {
      const [px, py] = out[out.length - 1], [x, y] = points[i];
      if (Math.hypot(x - px, y - py) > 0.05) out.push(points[i]);
    }
    return out;
  }

  function shorten(points, d) {
    const n = points.length, [x1, y1] = points[n - 1], [x0, y0] = points[n - 2];
    const len = Math.hypot(x1 - x0, y1 - y0) || 1;
    const k = Math.max(0, (len - d) / len);
    const copy = points.slice();
    copy[n - 1] = [x0 + (x1 - x0) * k, y0 + (y1 - y0) * k];
    return { points: copy, tip: [x1, y1], dir: [(x1 - x0) / len, (y1 - y0) / len] };
  }

  function el(name, attrs, parent) {
    const node = document.createElementNS(NS, name);
    for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
    parent.appendChild(node);
    return node;
  }

  function draw() {
    const fig = document.querySelector(".ol-figure");
    if (!fig) return;
    const flows = Array.from(fig.querySelectorAll(".ol-flow"));
    const old = fig.querySelector("svg.ol-wires");
    if (old) old.remove();
    if (!flows.length) return;
    const style = getComputedStyle(fig);
    const box = fig.getBoundingClientRect();
    const svg = el("svg", { class: "ol-wires", width: box.width, height: box.height,
                            viewBox: `0 0 ${box.width} ${box.height}` }, fig);
    const values = flows.map(f => parseFloat(f.dataset.value)).filter(v => !isNaN(v));
    const vmax = parseFloat(fig.dataset.flowMax) || Math.max(...values, 1);
    const wmax = (parseFloat(fig.dataset.flowWidth) || 3.6) * PX;
    const wmin = 0.7 * PX;
    const local = r => ({ left: r.left - box.left, right: r.right - box.left, top: r.top - box.top,
                          bottom: r.bottom - box.top, width: r.width, height: r.height });
    for (const f of flows) {
      const a = document.getElementById(f.dataset.from), b = document.getElementById(f.dataset.to);
      if (!a || !b) { console.error("ol-flow: missing element", f.dataset.from, f.dataset.to); continue; }
      const ra = local(a.getBoundingClientRect()), rb = local(b.getBoundingClientRect());
      const auto = sideOf(ra, rb);
      const s0 = f.dataset.fromSide || auto[0], s1 = f.dataset.toSide || auto[1];
      const p = anchor(ra, s0, parseFloat(f.dataset.fromAt || "0.5"));
      const q = anchor(rb, s1, parseFloat(f.dataset.toAt || "0.5"));
      const horizontal = s0 === "left" || s0 === "right";
      const kind = f.dataset.route || (horizontal ? "hvh" : "vhv");
      const value = parseFloat(f.dataset.value);
      const w = isNaN(value) ? 0.9 * PX : Math.max(wmin, wmax * value / vmax);
      // a jog smaller than the line itself reads as a kink: straighten it if the target allows
      const snap = Math.max(w, 3 * PX);
      if (kind === "hvh" && Math.abs(q[1] - p[1]) < snap && p[1] > rb.top && p[1] < rb.bottom) q[1] = p[1];
      if (kind === "vhv" && Math.abs(q[0] - p[0]) < snap && p[0] > rb.left && p[0] < rb.right) q[0] = p[0];
      let pts = simplify(route(p, q, kind, parseFloat(f.dataset.mid || "0.5")));
      const cls = ["energy", "data", "signal", "material", "control"].find(c => f.classList.contains(c)) || "ink";
      const colour = style.getPropertyValue(`--ol-${cls}`).trim() || "#222222";
      const head = Math.max(3.2 * PX, 2.1 * w);
      const heads = [];
      if (f.dataset.head !== "0") {
        const end = shorten(pts, head * 0.85); pts = end.points; heads.push(end);
        if (f.dataset.both === "1") {
          const start = shorten(pts.slice().reverse(), head * 0.85);
          pts = start.points.reverse(); heads.push(start);
        }
      }
      el("path", { d: "M" + pts.map(([x, y]) => `${x.toFixed(2)},${y.toFixed(2)}`).join(" L"),
                   fill: "none", stroke: colour, "stroke-width": w.toFixed(2), "stroke-linejoin": "round",
                   "stroke-linecap": "butt", ...(cls === "control" ? { "stroke-dasharray": `${3 * PX} ${2 * PX}` } : {}) }, svg);
      for (const h of heads) {
        const [tx, ty] = h.tip, [dx, dy] = h.dir, half = head * 0.42;
        const bx = tx - dx * head, by = ty - dy * head;
        el("path", { d: `M${tx},${ty} L${bx - dy * half},${by + dx * half} L${bx + dy * half},${by - dx * half} Z`,
                     fill: colour, stroke: "none" }, svg);
      }
      if (f.dataset.label) {
        // the longest leg carries the label, set beside the line (never on it)
        let best = 0, seg = [pts[0], pts[1]];
        for (let i = 1; i < pts.length; i++) {
          const L = Math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]);
          if (L > best) { best = L; seg = [pts[i - 1], pts[i]]; }
        }
        const mx = (seg[0][0] + seg[1][0]) / 2, my = (seg[0][1] + seg[1][1]) / 2;
        const vertical = Math.abs(seg[1][0] - seg[0][0]) < Math.abs(seg[1][1] - seg[0][1]);
        const side = f.dataset.labelSide || (vertical ? "right" : "above");
        const gap = w / 2 + 1.6 * PX;
        const attrs = { x: mx, y: my, "text-anchor": "middle", "dominant-baseline": "central" };
        if (side === "above") attrs.y = my - gap - 2.4 * PX;
        if (side === "below") attrs.y = my + gap + 2.4 * PX;
        if (side === "right") { attrs.x = mx + gap; attrs["text-anchor"] = "start"; }
        if (side === "left") { attrs.x = mx - gap; attrs["text-anchor"] = "end"; }
        const t = el("text", attrs, svg);
        t.textContent = f.dataset.label;
      }
    }
    document.documentElement.dataset.olDrawn = "1";
  }

  const go = () => (document.fonts ? document.fonts.ready.then(draw) : draw());
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", go); else go();
})();
