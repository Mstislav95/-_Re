"""PDF (vector, text in curves) -> DXF with real TEXT entities, without frame and title block."""
import json, math, sys
from collections import Counter
import pymupdf
import ezdxf
from ezdxf.enums import TextEntityAlignment

SRC, CLUSTERS, OUT = sys.argv[1], sys.argv[2], sys.argv[3]

# Sheet was printed "fit to page": GOST A4 frame 185 x 287 mm == 508.2 x 788.4 pt
MM_PER_PT = 185.0 / (566.16 - 57.96)
SCALE = 2.5                      # drawing scale M 1:2,5 -> model in real millimetres
K = MM_PER_PT * SCALE
X0, Y0 = 57.96, 815.04           # lower-left corner of the (removed) frame -> 0,0


def T(x, y):
    return ((x - X0) * K, (Y0 - y) * K)


page = pymupdf.open(SRC)[0]
drawings = page.get_drawings()
fills = [d for d in drawings if d['type'] == 'f']
clusters = json.load(open(CLUSTERS))


def is_frame_or_stamp(d):
    r = d['rect']
    if r.y0 >= 773.5:                                   # title block
        return True
    if d['type'] == 's' and abs(d['width'] - 0.6) < 0.01:  # frame + title block outline
        return True
    if d['type'] == 's' and r.height > 700:             # trim marks
        return True
    if d['type'] == 'f' and (r.y1 < 20 or r.x0 > 585):  # crop corner marks
        return True
    return False


# ---------------------------------------------------------------- texts
# cluster ids (from clusters.json) -> text; 'big' = 3.5 mm font, else 2.5 mm
TEXTS = [
    ([0, 1, 2, 3], 'Разрез В-В (листы 9, 10, 11)', 'big'),
    ([4, 5, 6], 'М 1:2,5', 'big'),
    ([10, 8, 7], 'min 150', ''), ([19, 18, 17], 'min 100', ''),
    ([12], 'Оконный блок', ''), ([13, 15], 'показан условно', ''),
    ([14], 'АК', ''), ([16], 'Ш1.Ц(Н)', ''), ([22], 'Ш2.Ц(Н)', ''),
    ([23], 'ПП 50,ПП 70,ПП 90', ''), ([24, 25, 26], 'ПИ 50,ПИ 70,ПИ 90', ''),
    ([27], 'ПКО.Ц', ''), ([28], 'ДЗ', ''), ([29], 'ЗН4', ''), ([30], 'ЗН4.1', ''),
    ([31], 'КО.Ц(Н).150', ''), ([32], 'КО.Ц(Н).250', ''), ([33], 'КО.Ц(Н).350', ''),
    ([34], 'ЗН4', ''), ([35], 'ЗН4.1', ''), ([36], '3', ''),
    ([37, 38], 'Утеплитель НГ', ''), ([39, 40], 'Утеплитель НГ', ''),
    ([41], 'НКК 50.Ц(Н)(А)', ''), ([42], 'НКК 70.Ц(Н)(А)', ''), ([43], 'НККУ.Ц(Н)(А)', ''),
    ([44], 'ПФ3.Ц(Н)', ''), ([45], 'ПН.Ц(Н)', ''), ([47], 'ОК.Ц', ''),
    ([48], 'min 30', 'vert'),
    ([49], 'ЗН4', ''), ([51], 'ЗН4.1', ''), ([50], 'ПНГ 0,3.Ц(Н)(А)', ''),
    ([53], 'СГ 4,8.19 Ц(Н)', ''), ([54], 'Керамогранитная', ''), ([56], 'плита', ''),
    ([55], '50-100', ''), ([60], '10±1', ''),
    ([61], 'КО.Ц(Н).150', ''), ([62], 'КО.Ц(Н).250', ''), ([63], 'КО.Ц(Н).350', ''),
    ([64], 'ЗН4/', ''), ([65], 'ЗН4.1', ''), ([66], 'ОК.Ц', ''),
]
text_fill_ids = set()
for ids, _, _ in TEXTS:
    for c in ids:
        text_fill_ids.update(clusters[c]['members'])

# ---------------------------------------------------------------- document
TEMPLATE = sys.argv[4] if len(sys.argv) > 4 else None
if TEMPLATE:   # empty R2000 document created by LibreDWG (dwgadd) -> DWG-conventional handles
    doc = ezdxf.readfile(TEMPLATE)
    doc.modelspace().delete_all_entities()
else:
    doc = ezdxf.new('R2000', setup=False)
doc.header['$INSUNITS'] = 4          # mm
doc.header['$MEASUREMENT'] = 1
doc.header['$LWDISPLAY'] = 1
doc.header['$DWGCODEPAGE'] = 'ANSI_1251'
msp = doc.modelspace()

style = doc.styles.new('GOST', dxfattribs={'font': 'isocpeur.ttf', 'oblique': 15.0, 'width': 1.0})

# stroke width (pt) -> (layer, lineweight in 1/100 mm)
LW = [(0.12, 5), (0.24, 9), (0.36, 13), (0.48, 18), (0.72, 25), (0.84, 30), (0.96, 35)]


def layer_for_width(w):
    pt, lw = min(LW, key=lambda t: abs(t[0] - w))
    return f'Линии {lw / 100:.2f}', lw


def ensure_layer(name, lw, color=7):
    if name not in doc.layers:
        doc.layers.add(name, color=color, lineweight=lw)


ensure_layer('Текст', 18, 7)
ensure_layer('Заливка', 0, 7)


# ---------------------------------------------------------------- geometry helpers
def subpaths(d):
    """Split a PyMuPDF path into vertex chains (pt coordinates)."""
    out, cur = [], []
    for it in d['items']:
        if it[0] == 'l':
            a, b = (it[1].x, it[1].y), (it[2].x, it[2].y)
            if cur and math.dist(cur[-1], a) < 1e-3:
                cur.append(b)
            else:
                if len(cur) > 1:
                    out.append(cur)
                cur = [a, b]
        elif it[0] == 'qu':
            q = it[1]
            if len(cur) > 1:
                out.append(cur)
            cur = []
            out.append([(q.ul.x, q.ul.y), (q.ur.x, q.ur.y), (q.lr.x, q.lr.y), (q.ll.x, q.ll.y), (q.ul.x, q.ul.y)])
        elif it[0] == 're':
            r = it[1]
            if len(cur) > 1:
                out.append(cur)
            cur = []
            out.append([(r.x0, r.y0), (r.x1, r.y0), (r.x1, r.y1), (r.x0, r.y1), (r.x0, r.y0)])
        else:
            raise ValueError(it[0])
    if len(cur) > 1:
        out.append(cur)
    res = []
    for ch in out:
        dd = [ch[0]]
        for p in ch[1:]:
            if math.dist(p, dd[-1]) > 1e-4:
                dd.append(p)
        if len(dd) > 1:
            res.append(dd)
    if d.get('closePath') and res and math.dist(res[-1][0], res[-1][-1]) > 1e-3:
        res[-1].append(res[-1][0])
    return res


def circle3(a, b, c):
    ax, ay = a; bx, by = b; cx, cy = c
    dd = 2 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    if abs(dd) < 1e-12:
        return None
    ux = ((ax * ax + ay * ay) * (by - cy) + (bx * bx + by * by) * (cy - ay) + (cx * cx + cy * cy) * (ay - by)) / dd
    uy = ((ax * ax + ay * ay) * (cx - bx) + (bx * bx + by * by) * (ax - cx) + (cx * cx + cy * cy) * (bx - ax)) / dd
    return (ux, uy), math.dist((ux, uy), a)


def cross(o, a, b):
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


ARC_TOL = 0.06    # mm (model) max deviation of original vertices from fitted arc
MIN_ARC_PTS = 4


def fits_arc(pts, i, j):
    """Points pts[i..j] lie on one arc (consistent turning, small deviation)?"""
    m = (i + j) // 2
    c = circle3(pts[i], pts[m], pts[j])
    if not c:
        return None
    (cx, cy), r = c
    if r > 2000:
        return None
    sgn = 0
    for k in range(i, j + 1):
        if abs(math.dist((cx, cy), pts[k]) - r) > ARC_TOL:
            return None
        if k > i:
            mid = ((pts[k - 1][0] + pts[k][0]) / 2, (pts[k - 1][1] + pts[k][1]) / 2)
            if r - math.dist((cx, cy), mid) > ARC_TOL * 2:
                return None
        if i < k < j:
            s = cross(pts[k - 1], pts[k], pts[k + 1])
            if abs(s) > 1e-9:
                ss = 1 if s > 0 else -1
                if sgn and ss != sgn:
                    return None
                sgn = ss
    # sweep angle must be < 360 and segments reasonably uniform
    seg = [math.dist(pts[k], pts[k + 1]) for k in range(i, j)]
    if max(seg) > 6 * (sum(seg) / len(seg)) or max(seg) > r * 0.55:
        return None
    return (cx, cy), r, sgn


def bulge_of(p0, p1, center, sgn):
    a0 = math.atan2(p0[1] - center[1], p0[0] - center[0])
    a1 = math.atan2(p1[1] - center[1], p1[0] - center[0])
    sweep = a1 - a0
    if sgn > 0:      # CCW
        while sweep <= 0:
            sweep += 2 * math.pi
    else:
        while sweep >= 0:
            sweep -= 2 * math.pi
    return math.tan(sweep / 4)


def to_bulge_poly(pts):
    """Return list of (x, y, bulge) replacing flattened arcs by bulge segments."""
    n = len(pts)
    out = []
    i = 0
    while i < n - 1:
        best = None
        j = i + MIN_ARC_PTS - 1
        while j < n:
            f = fits_arc(pts, i, j)
            if not f:
                break
            best = (j, f)
            j += 1
        if best:
            j, ((cx, cy), r, sgn) = best
            # split arcs with sweep >= 180 deg into two halves for robust bulges
            sweep = sum(abs(math.atan2(cross((cx, cy), pts[k], pts[k + 1]),
                                       (pts[k][0] - cx) * (pts[k + 1][0] - cx) + (pts[k][1] - cy) * (pts[k + 1][1] - cy)))
                        for k in range(i, j))
            if sweep > math.radians(300) and j - i >= 4:
                m = (i + j) // 2
                out.append((pts[i][0], pts[i][1], bulge_of(pts[i], pts[m], (cx, cy), sgn)))
                out.append((pts[m][0], pts[m][1], bulge_of(pts[m], pts[j], (cx, cy), sgn)))
            else:
                out.append((pts[i][0], pts[i][1], bulge_of(pts[i], pts[j], (cx, cy), sgn)))
            i = j
        else:
            out.append((pts[i][0], pts[i][1], 0.0))
            i += 1
    out.append((pts[-1][0], pts[-1][1], 0.0))
    # merge collinear straight segments
    res = [out[0]]
    for k in range(1, len(out)):
        p = out[k]
        if len(res) >= 2 and res[-2][2] == 0 and res[-1][2] == 0:
            a, b = res[-2], res[-1]
            if abs(cross(a[:2], b[:2], p[:2])) < 1e-6 * max(1, math.dist(a[:2], p[:2])) ** 2 and \
                    (b[0] - a[0]) * (p[0] - b[0]) + (b[1] - a[1]) * (p[1] - b[1]) > 0:
                res[-1] = p
                continue
        res.append(p)
    return res


def full_circle(pts):
    if len(pts) < 12 or math.dist(pts[0], pts[-1]) > 1e-3:
        return None
    cx = sum(p[0] for p in pts[:-1]) / (len(pts) - 1)
    cy = sum(p[1] for p in pts[:-1]) / (len(pts) - 1)
    rs = [math.dist((cx, cy), p) for p in pts[:-1]]
    r = sum(rs) / len(rs)
    if max(abs(x - r) for x in rs) < max(ARC_TOL, r * 0.004):
        return (cx, cy), r
    return None


stats = Counter()

# ---------------------------------------------------------------- strokes
def join_chains(chains, tol=2e-3):
    """Join chains through endpoints shared by exactly two chain ends (no branching)."""
    def key(p):
        return (round(p[0] / tol), round(p[1] / tol))
    node_edges = {}
    for i, c in enumerate(chains):
        node_edges.setdefault(key(c[0]), []).append(i)
        node_edges.setdefault(key(c[-1]), []).append(i)
    used = [False] * len(chains)

    def oriented(i, start_key):
        c = chains[i]
        return c if key(c[0]) == start_key else c[::-1]

    def extend(path):
        while True:
            k = key(path[-1])
            es = [e for e in node_edges[k] if not used[e]]
            if len(node_edges[k]) != 2 or len(es) != 1:
                return path
            e = es[0]
            used[e] = True
            path = path + oriented(e, k)[1:]
            if key(path[-1]) == key(path[0]):
                return path

    out = []
    for i, c in enumerate(chains):
        if used[i]:
            continue
        used[i] = True
        path = extend(list(c))
        if key(path[-1]) != key(path[0]) or len(path) < 3:
            back = extend(path[::-1])
            path = back
        out.append(path)
    return out


by_layer = {}
for d in drawings:
    if d['type'] != 's' or is_frame_or_stamp(d):
        continue
    layer, lw = layer_for_width(d['width'])
    ensure_layer(layer, lw)
    by_layer.setdefault(layer, []).extend([T(*p) for p in ch] for ch in subpaths(d))

for layer, chains in by_layer.items():
    stats['chains_in'] += len(chains)
    chains = join_chains(chains)
    stats['chains_out'] += len(chains)
    for pts in chains:
        c = full_circle(pts)
        if c:
            msp.add_circle(c[0], c[1], dxfattribs={'layer': layer})
            stats['circle'] += 1
            continue
        closed = len(pts) > 2 and math.dist(pts[0], pts[-1]) < 2e-3
        if len(pts) == 2:
            msp.add_line(pts[0], pts[1], dxfattribs={'layer': layer})
            stats['line'] += 1
            continue
        bp = to_bulge_poly(pts)
        if closed:
            bp = bp[:-1]
        if len(bp) == 2 and bp[0][2] == 0 and not closed:
            msp.add_line(bp[0][:2], bp[1][:2], dxfattribs={'layer': layer})
            stats['line'] += 1
            continue
        msp.add_lwpolyline(bp, format='xyb', close=closed, dxfattribs={'layer': layer})
        stats['lwpolyline'] += 1
        stats['arcs'] += sum(1 for p in bp if p[2])

# ---------------------------------------------------------------- non-text fills -> solid hatch
for i, d in enumerate(fills):
    if i in text_fill_ids or is_frame_or_stamp(d):
        continue
    if d['rect'].width < 0.05 or d['rect'].height < 0.05:
        stats['skip_degenerate_fill'] += 1
        continue
    loops = []
    for ch in subpaths(d):
        if len(ch) < 3:
            continue
        pts = [T(*p) for p in ch]
        if math.dist(pts[0], pts[-1]) < 1e-4:
            pts = pts[:-1]
        if len(pts) >= 3:
            loops.append(pts)
    if not loops:
        stats['skip_degenerate_fill'] += 1
        continue
    h = msp.add_hatch(color=256, dxfattribs={'layer': 'Заливка', 'hatch_style': 0})
    h.set_solid_fill(color=256)
    for k, lp in enumerate(loops):
        h.paths.add_polyline_path(lp, is_closed=True, flags=1 if k == 0 else 0)
    stats['hatch'] += 1

# ---------------------------------------------------------------- texts
H_SMALL = 2.5 * SCALE
H_BIG = 3.5 * SCALE
for ids, s, kind in TEXTS:
    members = [m for c in ids for m in clusters[c]['members']]
    rects = [fills[m]['rect'] for m in members]
    x0 = min(r.x0 for r in rects); x1 = max(r.x1 for r in rects)
    y0 = min(r.y0 for r in rects); y1 = max(r.y1 for r in rects)
    h = H_BIG if kind == 'big' else H_SMALL
    if kind == 'vert':
        base_x = Counter(round(r.x1, 1) for r in rects).most_common(1)[0][0]
        ins = T(base_x, y1)
        rot = 90.0
    else:
        base_y = Counter(round(r.y1, 1) for r in rects).most_common(1)[0][0]
        ins = T(x0, base_y)
        rot = 0.0
    msp.add_text(s, height=h, rotation=rot, dxfattribs={
        'layer': 'Текст', 'style': 'GOST', 'oblique': 15.0, 'insert': ins})
    stats['text'] += 1

from ezdxf import bbox
ext = bbox.extents(msp, fast=True)
msp.dxf.extmin = ext.extmin
msp.dxf.extmax = ext.extmax
doc.set_modelspace_vport(height=ext.size.y * 1.05, center=ext.center)
doc.header['$DIMSTYLE'] = 'Standard'
doc.encoding = 'cp1251'
doc.saveas(OUT)
print(dict(stats))
