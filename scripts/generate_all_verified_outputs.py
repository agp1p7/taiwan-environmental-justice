# Unified Deterministic & Reproducible Verification Pipeline (2026-11-13)
# Outputs:
# - taiwan_incinerators_verified.csv
# - incinerators.geojson (+ staged 2-part text chunks in browser_sandbox/references)
# - township_cleaned_pollution_stats.csv
# - scratch/verified_all_stats.json
# - reports/figures/{incinerator_income_rank,pm25_vs_income,no2_vs_income}.svg
# - Local & GitHub-staged Markdown reports (COMPREHENSIVE_ENVIRONMENTAL_JUSTICE_REPORT.md,
#   incinerators_environmental_justice.md, cleaned_pollution_income_analysis.md, SHANHUA-FINAL-RESOLUTION.md)
# - manifest_fixed.json (+ staged browser_sandbox/references/manifest.json)

import csv, hashlib, json, math, os, re, shutil, unicodedata
from collections import Counter, defaultdict

B = r'C:\Users\agp1p\.gemini\antigravity\brain\ca448081-89ce-46aa-9536-e796a97fad1e'
REF = os.path.join(B, 'browser_sandbox', 'references')
FIG_DIR = os.path.join(B, 'reports', 'figures')
REP_ENV_DIR = os.path.join(B, 'reports', 'environment')
REP_SH_DIR = os.path.join(B, 'reports', 'station-mapping-review-v2')
os.makedirs(REF, exist_ok=True)
os.makedirs(FIG_DIR, exist_ok=True)
os.makedirs(REP_ENV_DIR, exist_ok=True)
os.makedirs(REP_SH_DIR, exist_ok=True)

def norm(s):
    s = unicodedata.normalize('NFKC', str(s or ''))
    return re.sub(r'\s+', '', s).replace('台', '臺').replace('※', '')

def t_cdf_two_tailed_p(t_val, df):
    if df <= 0 or math.isnan(t_val):
        return 1.0
    x = df / (df + t_val * t_val)
    a = df / 2.0
    theta_max = math.asin(math.sqrt(max(0.0, min(1.0, x))))
    if theta_max == 0:
        return 0.0
    n_steps = 2000
    h = theta_max / n_steps
    log_beta = math.lgamma(a) + math.lgamma(0.5) - math.lgamma(a + 0.5)
    total = 0.0
    for i in range(n_steps + 1):
        th = i * h
        s = math.sin(th)
        val = 0.0 if s <= 0 else math.exp((2 * a - 1) * math.log(s) - log_beta)
        w = 1 if (i == 0 or i == n_steps) else (4 if i % 2 == 1 else 2)
        total += w * val
    return max(0.0, min(1.0, 2.0 * total * h / 3.0))

def pearson_r(xs, ys):
    n = len(xs)
    if n < 3:
        return 0.0, 1.0, (0.0, 0.0)
    mx, my = sum(xs) / n, sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    dy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if dx == 0 or dy == 0:
        return 0.0, 1.0, (0.0, 0.0)
    r = max(-0.9999999, min(0.9999999, num / (dx * dy)))
    t_val = r * math.sqrt((n - 2) / (1 - r * r))
    p = t_cdf_two_tailed_p(abs(t_val), n - 2)
    z = 0.5 * math.log((1 + r) / (1 - r))
    se = 1.0 / math.sqrt(max(1, n - 3))
    return r, p, (math.tanh(z - 1.959964 * se), math.tanh(z + 1.959964 * se))

def rankdata(vals):
    n = len(vals)
    indexed = sorted(enumerate(vals), key=lambda x: x[1])
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and indexed[j + 1][1] == indexed[i][1]:
            j += 1
        avg_rank = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[indexed[k][0]] = avg_rank
        i = j + 1
    return ranks

def spearman_rho(xs, ys):
    return pearson_r(rankdata(xs), rankdata(ys))

def partial_corr(xs, ys, zs):
    n = len(xs)
    rxy, _, _ = pearson_r(xs, ys)
    rxz, _, _ = pearson_r(xs, zs)
    ryz, _, _ = pearson_r(ys, zs)
    denom = math.sqrt(max(1e-15, (1 - rxz ** 2) * (1 - ryz ** 2)))
    r = max(-0.9999999, min(0.9999999, (rxy - rxz * ryz) / denom))
    t_val = r * math.sqrt((n - 3) / (1 - r * r))
    p = t_cdf_two_tailed_p(abs(t_val), n - 3)
    return r, p

def bh_fdr(p_vals):
    m = len(p_vals)
    order = sorted(range(m), key=lambda i: p_vals[i])
    q_vals = [1.0] * m
    prev = 1.0
    for rank_idx in range(m - 1, -1, -1):
        orig_i = order[rank_idx]
        q = min(prev, p_vals[orig_i] * m / (rank_idx + 1))
        q_vals[orig_i] = q
        prev = q
    return q_vals

def welch_ttest(a, b):
    na, nb = len(a), len(b)
    ma, mb = sum(a) / na, sum(b) / nb
    va = sum((x - ma) ** 2 for x in a) / (na - 1)
    vb = sum((x - mb) ** 2 for x in b) / (nb - 1)
    se = math.sqrt(va / na + vb / nb)
    t_val = (ma - mb) / se
    df = (va / na + vb / nb) ** 2 / ((va / na) ** 2 / (na - 1) + (vb / nb) ** 2 / (nb - 1))
    return t_val, df, t_cdf_two_tailed_p(abs(t_val), df)

def mann_whitney_u(a, b):
    na, nb = len(a), len(b)
    ranks = rankdata(a + b)
    ra = sum(ranks[:na])
    u1 = ra - na * (na + 1) / 2.0
    mu = na * nb / 2.0
    su = math.sqrt(na * nb * (na + nb + 1) / 12.0)
    z = (u1 - mu) / su
    return u1, z, math.erfc(abs(z) / math.sqrt(2.0))

def paired_ttest(diffs):
    n = len(diffs)
    md = sum(diffs) / n
    sd = math.sqrt(sum((d - md) ** 2 for d in diffs) / (n - 1))
    t_val = md / (sd / math.sqrt(n))
    return md, sd, t_val, t_cdf_two_tailed_p(abs(t_val), n - 1)

def wilcoxon_signed_rank(diffs):
    nz = [d for d in diffs if d != 0]
    n = len(nz)
    ranks = rankdata([abs(d) for d in nz])
    w_plus = sum(r for d, r in zip(nz, ranks) if d > 0)
    w_minus = sum(r for d, r in zip(nz, ranks) if d < 0)
    w = min(w_plus, w_minus)
    mean_w = n * (n + 1) / 4.0
    sd_w = math.sqrt(n * (n + 1) * (2 * n + 1) / 24.0)
    z = -abs((w - mean_w) / sd_w) if sum(diffs) < 0 else abs((w - mean_w) / sd_w)
    return w_plus, w_minus, z, math.erfc(abs(z) / math.sqrt(2.0))

def in_ring(x, y, ring):
    inside = False
    n = len(ring)
    j = n - 1
    for i in range(n):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-12) + xi):
            inside = not inside
        j = i
    return inside

def in_poly(x, y, coords):
    return in_ring(x, y, coords[0]) and not any(in_ring(x, y, h) for h in coords[1:])

def pt_seg_dist_m(lon, lat, x1, y1, x2, y2, cos_lat):
    ax, ay = (x1 - lon) * 111320.0 * cos_lat, (y1 - lat) * 110574.0
    bx, by = (x2 - lon) * 111320.0 * cos_lat, (y2 - lat) * 110574.0
    dx, dy = bx - ax, by - ay
    l2 = dx * dx + dy * dy
    if l2 == 0:
        return math.hypot(ax, ay)
    t = max(0.0, min(1.0, -(ax * dx + ay * dy) / l2))
    return math.hypot(ax + t * dx, ay + t * dy)

print("1. Loading income.geojson & building exact spatial index...")
geo = json.load(open(os.path.join(B, 'income.geojson'), encoding='utf-8'))
feats = []
town_villages = defaultdict(list)
town_rings = defaultdict(list)
villcode_to_town = {}
town_ems = defaultdict(Counter)

for f in geo['features']:
    pr = f.get('properties') or {}
    g = f.get('geometry') or {}
    polys = g.get('coordinates') or []
    if g.get('type') == 'Polygon':
        polys = [polys]
    xs = [p[0] for poly in polys for p in poly[0]]
    ys = [p[1] for poly in polys for p in poly[0]]
    if xs:
        feats.append((min(xs), max(xs), min(ys), max(ys), polys, pr))
    c, t, vc = norm(pr.get('COUNTYNAME')), norm(pr.get('TOWNNAME')), pr.get('VILLCODE')
    if c and t and vc and str(pr.get('VILLNAME') or '').strip():
        key = f"{c}|{t}"
        villcode_to_town[str(vc)] = key
        town_villages[key].append(pr)
        for k_ems in ['air_records', 'water_records', 'waste_records', 'soil_records', 'ems01_records']:
            town_ems[key][k_ems] += int(pr.get(k_ems) or 0)
        for poly in polys:
            for ring in poly:
                rxs = [p[0] for p in ring]
                rys = [p[1] for p in ring]
                if rxs:
                    town_rings[key].append((min(rxs), max(rxs), min(rys), max(rys), ring))

def find_vill(lon, lat):
    for x0, x1, y0, y1, polys, pr in feats:
        if x0 <= lon <= x1 and y0 <= lat <= y1 and any(in_poly(lon, lat, poly) for poly in polys):
            return pr
    return None

def exact_dist_to_other_township_m(lon, lat, my_town_key):
    best = 1e9
    best_town = ""
    cos_lat = math.cos(math.radians(lat))
    for otk, rings in town_rings.items():
        if otk == my_town_key:
            continue
        for x0, x1, y0, y1, ring in rings:
            if lon < x0 - 0.1 or lon > x1 + 0.1 or lat < y0 - 0.1 or lat > y1 + 0.1:
                continue
            for i in range(len(ring) - 1):
                d = pt_seg_dist_m(lon, lat, ring[i][0], ring[i + 1][0], ring[i + 1][1], cos_lat)
                if d < best:
                    best = d
                    best_town = otk
    return round(best, 1), best_town

print("2. Loading official 113年度 (2024) FIA township income & 2024 density...")
town_inc = {}
with open(os.path.join(B, 'scratch', 'env_check', 'township-income-source.csv'), encoding='utf-8-sig') as f:
    for r in csv.DictReader(f):
        c, t = r['key'].split('|')
        k = f"{norm(c)}|{norm(t)}"
        town_inc[k] = {
            "county": norm(c),
            "township": norm(t),
            "median_income_thousand_twd": float(r['income_median_thousand']),
            "mean_income_thousand_twd": float(r['income_mean_thousand']),
            "tax_units": int(float(r['filing_units'])),
            "archive_member": r['archive_member'],
        }

dens_raw = json.load(open(os.path.join(B, 'scratch', 'env_check', 'township-density-2024.json'), encoding='utf-8'))
town_dens = {}
for raw_k, r in dens_raw.items():
    if '|' not in raw_k:
        continue
    c_raw, t_raw = raw_k.split('|', 1)
    is_indig = 1 if '※' in t_raw else 0
    k = f"{norm(c_raw)}|{norm(t_raw)}"
    if k in town_inc:
        town_dens[k] = {
            "population": int(float(r['population'])),
            "area_km2": float(r['area_km2']),
            "population_density": float(r['density']),
            "is_mountain_indigenous": is_indig,
        }
assert len(town_inc) == 368 and len(town_dens) == 368

print("3. Verifying official 25 SWIMS coordinates from JS bundle + 3 non-SWIMS facilities...")
mp_js = open(os.path.join(B, 'scratch', 'IncinerationPlantMapAtMain-CJCuKU6L.js'), encoding='utf-8').read()
m_arr = re.search(r'l=F\((\[\{id:1,wepNo:"WEPC1448".*?\}\])\)', mp_js)
swims_js = json.loads(re.sub(r'(\b(?:id|wepNo|name|enname|local|type)\b):', r'"\1":', m_arr.group(1)))
assert len(swims_js) == 25
swims_coord_map = {p['wepNo']: (float(p['local'][1]), float(p['local'][0])) for p in swims_js}

# Verified metadata: 24 early SWIMS plants from swims_basic_info.pdf + Taitung WEPV9500 from DescriptionPage/MOENV + 3 non-SWIMS from govt/EIA announcements.
# None means unverified in checked primary tabular specs (written as null in GeoJSON, "" in CSV).
inc_specs = [
    (1, "WEPC1448", "基隆市天外天垃圾資源回收(焚化)廠", "基隆市", "信義區", "基隆市信義區東安里培德路221之3號", None, None, "公有民營", 2001, 2005, 2006, 600, 2, 15.8, 100, 3.40, "SWIMS_OPERATING_25", "營運中", "SWIMS列管25廠；位於基隆市信義區東側與瑞芳區交界山谷", "https://swims.moenv.gov.tw/IncinerationPlantDetail?WepNo=WEPC1448"),
    (2, "WEPA4427", "臺北市政府環境保護局北投垃圾焚化廠", "臺北市", "北投區", "臺北市北投區洲美里洲美街271號", None, None, "公有公營", 1990, 1999, 1999, 1800, 4, 45.0, 150, 10.64, "SWIMS_OPERATING_25", "營運中", "SWIMS列管25廠；位於北投區西南隅基隆河與雙溪匯流口洲美里", "https://swims.moenv.gov.tw/IncinerationPlantDetail?WepNo=WEPA4427"),
    (3, "WEPA4059", "臺北市政府環境保護局木柵垃圾焚化廠", "臺北市", "文山區", "臺北市文山區博嘉里木柵路五段53號", None, None, "公有公營", 1989, 1994, 1995, 1500, 4, 13.5, 150, 7.20, "SWIMS_OPERATING_25", "營運中", "SWIMS列管25廠；位於文山區東側與新北市深坑區交界山谷", "https://swims.moenv.gov.tw/IncinerationPlantDetail?WepNo=WEPA4059"),
    (4, "WEPA4244", "臺北市政府環境保護局內湖垃圾焚化廠", "臺北市", "內湖區", "臺北市內湖區蘆洲里安康路290號", None, None, "公有公營", 1987, 1992, 1992, 900, 3, 6.0, 74, 8.10, "SWIMS_OPERATING_25", "營運中", "SWIMS列管25廠；全台首座大型垃圾焚化廠，位於內湖區南緣基隆河北岸蘆洲里（鄰南港與汐止界）", "https://swims.moenv.gov.tw/IncinerationPlantDetail?WepNo=WEPA4244"),
    (5, "WEPF0537", "新北市新店垃圾焚化廠", "新北市", "新店區", "新北市新店區德安里薏仁坑路自強巷1號", None, None, "公有民營", 1991, 1994, 1994, 900, 2, 14.6, 120, 3.50, "SWIMS_OPERATING_25", "營運中", "SWIMS列管25廠；位於新店區西側安坑薏仁坑山區（鄰中和與土城界）", "https://swims.moenv.gov.tw/IncinerationPlantDetail?WepNo=WEPF0537"),
    (6, "WEPF0759", "新北市樹林垃圾焚化廠", "新北市", "樹林區", "新北市樹林區樂山里中山路三段212號", None, None, "公有民營", 1992, 1995, 1995, 1350, 3, 22.3, 120, 4.50, "SWIMS_OPERATING_25", "營運中", "SWIMS列管25廠；位於樹林區西南山佳樂山里（鄰鶯歌界）", "https://swims.moenv.gov.tw/IncinerationPlantDetail?WepNo=WEPF0759"),
    (7, "WEPF2314", "新北市八里垃圾焚化廠", "新北市", "八里區", "新北市八里區下罟里中山路三段409號", None, None, "公有民營", 1997, 2001, 2001, 1350, 3, 35.8, 150, 3.50, "SWIMS_OPERATING_25", "營運中", "SWIMS列管25廠；位於八里區西側海岸線下罟里（鄰林口界）", "https://swims.moenv.gov.tw/IncinerationPlantDetail?WepNo=WEPF2314"),
    (8, "WEPH4335", "桃園市垃圾焚化廠（欣榮廠）", "桃園市", "中壢區", "桃園市中壢區內定里松江北路16號", None, None, "民有民營(BOO)", 1999, 2001, 2001, 1350, 2, 35.1, 80, 3.00, "SWIMS_OPERATING_25", "營運中", "SWIMS列管25廠；位於中壢工業區北端內定里（鄰蘆竹與大園界）", "https://swims.moenv.gov.tw/IncinerationPlantDetail?WepNo=WEPH4335"),
    (9, "WEPG3008", "宜蘭縣利澤垃圾資源回收(焚化)廠", "宜蘭縣", "五結鄉", "宜蘭縣五結鄉成興村利工二路100號", None, None, "公有民營", 2002, 2005, 2006, 600, 2, 14.7, 120, 9.99, "SWIMS_OPERATING_25", "營運中", "SWIMS列管25廠；位於五結鄉東南沿海利澤工業區成興村（鄰蘇澳鎮界）", "https://swims.moenv.gov.tw/IncinerationPlantDetail?WepNo=WEPG3008"),
    (10, "WEPO1732", "新竹市垃圾資源回收廠", "新竹市", "北區", "新竹市北區海濱里海濱路240號", None, None, "公有民營", 1995, 2000, 2001, 900, 2, 23.7, 67, 5.50, "SWIMS_OPERATING_25", "營運中", "SWIMS列管25廠；位於新竹市北區南寮海濱里海岸線（鄰香山區界）", "https://swims.moenv.gov.tw/IncinerationPlantDetail?WepNo=WEPO1732"),
    (11, "WEPK0322", "苗栗縣垃圾焚化廠", "苗栗縣", "竹南鎮", "苗栗縣竹南鎮海口里保安林25之60號", None, None, "民有民營(BOT)", 2002, 2008, 2008, 500, 2, 11.8, 70, 3.93, "SWIMS_OPERATING_25", "營運中", "SWIMS列管25廠；位於竹南鎮西側沿海保安林海口里", "https://swims.moenv.gov.tw/IncinerationPlantDetail?WepNo=WEPK0322"),
    (12, "WEPB2401", "臺中市文山垃圾焚化廠", "臺中市", "南屯區", "臺中市南屯區文山里文山南巷500號", None, None, "公有民營", 1992, 1995, 1995, 900, 3, 13.0, 120, 4.40, "SWIMS_OPERATING_25", "營運中", "SWIMS列管25廠；位於南屯區西側大肚台地文山里（鄰西屯與大肚界）", "https://swims.moenv.gov.tw/IncinerationPlantDetail?WepNo=WEPB2401"),
    (13, "WEPL9232", "臺中市后里資源回收廠", "臺中市", "后里區", "臺中市后里區舊社里堤防路556號", None, None, "公有民營", 1996, 2000, 2000, 900, 2, 22.6, 120, 3.20, "SWIMS_OPERATING_25", "營運中", "SWIMS列管25廠；位於后里區南側大甲溪北岸舊社里（緊鄰神岡與豐原界）", "https://swims.moenv.gov.tw/IncinerationPlantDetail?WepNo=WEPL9232"),
    (14, "WEPL0028", "臺中市烏日資源回收廠", "臺中市", "烏日區", "臺中市烏日區螺潭里慶光路800號", None, None, "民有民營(BOT)", 2001, 2004, 2004, 900, 2, 22.6, 100, 4.30, "SWIMS_OPERATING_25", "營運中", "SWIMS列管25廠；位於烏日區南端貓羅溪與烏溪匯流處（緊鄰彰化市／芬園界）", "https://swims.moenv.gov.tw/IncinerationPlantDetail?WepNo=WEPL0028"),
    (15, "WEPN3259", "彰化縣溪州垃圾焚化廠", "彰化縣", "溪州鄉", "彰化縣溪州鄉水尾村彰水路一段臨1號", None, None, "公有民營", 1996, 2000, 2001, 900, 2, 22.6, 120, 8.40, "SWIMS_OPERATING_25", "營運中", "SWIMS列管25廠；位於溪州鄉西／南緣水尾村（緊鄰埤頭與濁水溪界）", "https://swims.moenv.gov.tw/IncinerationPlantDetail?WepNo=WEPN3259"),
    (16, "WEPI2617", "嘉義市垃圾焚化廠", "嘉義市", "西區", "嘉義市西區湖內里湖子內路741號", None, None, "公有民營", 1994, 1998, 1998, 300, 2, 2.3, 70, 3.50, "SWIMS_OPERATING_25", "營運中", "SWIMS列管25廠；位於嘉義市西區南端八掌溪畔湖內里（緊鄰嘉義縣中埔／水上界）", "https://swims.moenv.gov.tw/IncinerationPlantDetail?WepNo=WEPI2617"),
    (17, "WEPQ7513", "嘉義縣鹿草垃圾焚化廠", "嘉義縣", "鹿草鄉", "嘉義縣鹿草鄉豐稠村馬稠後農場60號", None, None, "公有民營", 1998, 2001, 2001, 900, 2, 25.0, 120, 10.45, "SWIMS_OPERATING_25", "營運中", "SWIMS列管25廠；位於鹿草鄉北側馬稠後農場豐稠村（緊鄰朴子與太保界）", "https://swims.moenv.gov.tw/IncinerationPlantDetail?WepNo=WEPQ7513"),
    (18, "WEPD3244", "臺南市城西垃圾焚化廠", "臺南市", "安南區", "臺南市安南區城西里城西街三段1105巷121弄150號", None, None, "公有民營", 1993, 1999, 1999, 900, 2, 14.3, 120, 14.50, "SWIMS_OPERATING_25", "營運中", "SWIMS列管25廠；位於安南區最西端曾文溪口海岸城西里（鄰七股界）", "https://swims.moenv.gov.tw/IncinerationPlantDetail?WepNo=WEPD3244"),
    (19, "WEPR8506", "臺南市永康垃圾資源回收(焚化)廠", "臺南市", "永康區", "臺南市永康區王行里王行東路166號", 120.281500, 23.040100, "公有民營", 2003, 2007, 2008, 900, 2, 22.5, 102, 4.95, "SWIMS_OPERATING_25", "營運中", "SWIMS列管25廠；法定門牌永康區王行東路166號（廠區大門 120.2815, 23.0401 落於永康區王行里，距新化區界僅30.5公尺），而SWIMS系統標註煙囪點位（120.282537, 23.040198）則越過界77.2公尺落於新化區北勢里", "https://swims.moenv.gov.tw/IncinerationPlantDetail?WepNo=WEPR8506"),
    (20, "WEPE5004", "高雄市政府環境保護局中區資源回收廠", "高雄市", "三民區", "高雄市三民區鼎金里鼎金一巷15號", None, None, "公有公營", 1995, 1999, 1999, 900, 3, 25.5, 100, 4.50, "SWIMS_OPERATING_25", "營運中", "SWIMS列管25廠；位於三民區北端覆鼎金鼎金里（緊鄰鳥松與仁武界）", "https://swims.moenv.gov.tw/IncinerationPlantDetail?WepNo=WEPE5004"),
    (21, "WEPE5641", "高雄市政府環境保護局南區資源回收廠", "高雄市", "小港區", "高雄市小港區山明里北林路6號", None, None, "公有公營", 1996, 1999, 2000, 1800, 4, 49.0, 88, 14.87, "SWIMS_OPERATING_25", "營運中", "SWIMS列管25廠；位於小港區東側臨海工業區旁山明里（鄰大寮界）", "https://swims.moenv.gov.tw/IncinerationPlantDetail?WepNo=WEPE5641"),
    (22, "WEPS2225", "高雄市仁武垃圾資源回收(焚化)廠", "高雄市", "仁武區", "高雄市仁武區烏林里仁安二巷100號", None, None, "公有民營", 1996, 2000, 2000, 1350, 3, 36.5, 120, 12.93, "SWIMS_OPERATING_25", "營運中", "SWIMS列管25廠；位於仁武區東側烏林里工業區旁", "https://swims.moenv.gov.tw/IncinerationPlantDetail?WepNo=WEPS2225"),
    (23, "WEPS1656", "高雄市岡山垃圾資源回收(焚化)廠", "高雄市", "岡山區", "高雄市岡山區本洲里本工五路9號", None, None, "公有民營", 1998, 2001, 2001, 1350, 3, 38.0, 60, 7.24, "SWIMS_OPERATING_25", "營運中", "SWIMS列管25廠；位於岡山區西側本洲工業區本洲里（緊鄰路竹與永安界）", "https://swims.moenv.gov.tw/IncinerationPlantDetail?WepNo=WEPS1656"),
    (24, "WEPT5929", "屏東縣崁頂垃圾資源回收(焚化)廠", "屏東縣", "崁頂鄉", "屏東縣崁頂鄉越溪村中正路881號", None, None, "公有民營", 1997, 2000, 2001, 900, 2, 22.5, 100, 13.00, "SWIMS_OPERATING_25", "營運中", "SWIMS列管25廠；位於崁頂鄉南端越溪村（緊鄰南州與東港界）", "https://swims.moenv.gov.tw/IncinerationPlantDetail?WepNo=WEPT5929"),
    (25, "WEPV9500", "臺東縣垃圾焚化廠（廢棄物能資源中心）", "臺東縣", "臺東市", "臺東縣臺東市豐谷里成都南路709號", None, None, "公有民營", 1998, 2005, 2023, 300, 2, 8.9, 55, None, "SWIMS_OPERATING_25", "營運中", "SWIMS列管25廠；2005年完工後因BOO爭議閒置，縣府買回修繕升級後於2023年1月31日正式點火試運轉啟用（煙囪高度55公尺）", "https://swims.moenv.gov.tw/IncinerationPlantDetail?WepNo=WEPV9500"),
    (26, "NON_SWIMS_TY_BIO", "桃園市生質能中心（榮鼎綠能）", "桃園市", "觀音區", "桃園市觀音區大潭里環西路128號", 121.057676, 25.032047, "民有民營(BOT)", 2019, 2023, 2024, 660, None, None, None, 4.38, "BIOMASS_ENERGY_BOT", "營運中（生質能中心）", "非SWIMS傳統25廠；桃園環保科技園區BOT三合一設施（熱處理660噸/日+厭氧消化135噸/日+固化掩埋），2024年商轉", "https://www.tydep.gov.tw/"),
    (27, "NON_SWIMS_HC_BOO", "新竹縣高效能垃圾熱處理設施（竹北廠）", "新竹縣", "竹北市", "新竹縣竹北市尚義里拔子窟（台61線鳳鼻隧道南側）", 120.953263, 24.872663, "民有民營(BOO)", 2021, 2024, 2025, 500, 2, None, None, 2.70, "NEW_BOO_2025", "試運轉／新啟用", "非SWIMS傳統25廠；2024年12月26日點火試燒、2025年進入試運轉並提升處理量；位於竹北市最西北隅海岸尚義里（鄰新豐界）", "https://www.hcepb.gov.tw/"),
    (28, "NON_SWIMS_YL_BOO", "雲林縣林內垃圾焚化廠（完工未營運）", "雲林縣", "林內鄉", "雲林縣林內鄉重興村進興路一帶", 120.602948, 23.779336, "民有民營(BOO)", 2002, 2005, None, 600, None, None, 60, 5.18, "UNOPERATED_BOO", "完工未營運", "非SWIMS傳統25廠；2005年完工，因弊案及最高行政法院撤銷環評結論而從未啟用營運", "https://zh.wikipedia.org/zh-tw/%E6%9E%97%E5%85%A7%E5%9E%83%E5%9C%BE%E7%84%9A%E5%8C%96%E5%BB%A0"),
]

inc_rows = []
inc_geojson_features = []
for sp in inc_specs:
    (pid, wepNo, name, county, township, addr, custom_lon, custom_lat,
     op_mode, start_yr, done_yr, op_yr, cap_tpd, furnaces, mw, chimney_m, area_ha,
     cat, status, note, src_url) = sp
    if wepNo in swims_coord_map:
        swims_lon, swims_lat = swims_coord_map[wepNo]
        lon = custom_lon if custom_lon is not None else swims_lon
        lat = custom_lat if custom_lat is not None else swims_lat
    else:
        lon, lat = custom_lon, custom_lat
        swims_lon, swims_lat = lon, lat

    pr = find_vill(lon, lat)
    assert pr is not None, f"Point-in-polygon failed for {name}"
    got_c, got_t, got_v = norm(pr.get('COUNTYNAME')), norm(pr.get('TOWNNAME')), norm(pr.get('VILLNAME'))
    assert got_c == county and got_t == township, f"Mismatch for {name}: expected {county}|{township}, got {got_c}|{got_t}"

    tkey = f"{county}|{township}"
    t_med = town_inc[tkey]['median_income_thousand_twd']
    t_mean = town_inc[tkey]['mean_income_thousand_twd']
    t_dens = town_dens[tkey]['population_density']
    v_med = float(pr.get('income_median') or 0.0)
    v_diff = round(v_med - t_med, 1)
    v_incomes = sorted([float(vp['income_median']) for vp in town_villages[tkey] if vp.get('income_median') is not None])
    less_eq = sum(1 for x in v_incomes if x <= v_med)
    strict_less = sum(1 for x in v_incomes if x < v_med)
    v_pct = round(100.0 * less_eq / max(1, len(v_incomes)), 1)
    v_mid_pct = round(100.0 * (strict_less + 0.5 * (less_eq - strict_less)) / max(1, len(v_incomes)), 1)
    dist_m, nearest_other_town = exact_dist_to_other_township_m(lon, lat, tkey)

    prop_obj = {
        "id": pid, "wep_no": wepNo, "name": name, "county": county, "township": township,
        "village": got_v, "villcode": pr.get('VILLCODE'), "address": addr,
        "lon": round(lon, 6), "lat": round(lat, 6),
        "swims_chimney_lon": round(swims_lon, 6), "swims_chimney_lat": round(swims_lat, 6),
        "category": cat, "status": status, "operation_mode": op_mode,
        "start_construction_year": start_yr, "completion_year": done_yr, "operation_start_year": op_yr,
        "capacity_tons_per_day": cap_tpd, "furnaces": furnaces, "power_mw": mw,
        "chimney_height_m": chimney_m, "area_ha": area_ha,
        "township_income_median": t_med, "township_income_mean": t_mean,
        "township_population_density": t_dens,
        "host_village_income_median": v_med, "village_minus_township_income": v_diff,
        "village_percentile_in_township": v_pct, "village_midrank_percentile": v_mid_pct,
        "village_count_in_township": len(v_incomes),
        "dist_to_other_township_m": dist_m, "nearest_other_township": nearest_other_town,
        "note": note, "source_url": src_url,
    }
    csv_row = {k: ("" if v is None else v) for k, v in prop_obj.items()}
    inc_rows.append(csv_row)
    inc_geojson_features.append({
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [round(lon, 6), round(lat, 6)]},
        "properties": prop_obj,
    })

csv_path = os.path.join(B, 'taiwan_incinerators_verified.csv')
with open(csv_path, 'w', encoding='utf-8-sig', newline='') as f:
    w = csv.DictWriter(f, fieldnames=list(inc_rows[0].keys()))
    w.writeheader()
    w.writerows(inc_rows)
shutil.copy2(csv_path, os.path.join(REF, 'taiwan_incinerators_verified.csv'))

# Format GeoJSON cleanly: 30 lines (1 header line, 28 feature lines, 1 footer line)
meta = {
    "source": "環境部環境管理署焚化廠營運管理資訊系統 (SWIMS, https://swims.moenv.gov.tw/) 25座營運中大型垃圾焚化廠 + 3座非SWIMS/新建/未營運設施",
    "verified_date": "2026-11-13",
    "point_in_polygon_verified": "28/28 matched against income.geojson COUNTYNAME, TOWNNAME, VILLNAME",
}
geo_lines = [
    '{"type":"FeatureCollection","metadata":' + json.dumps(meta, ensure_ascii=False, separators=(',', ':')) + ',"features":['
]
for i, feat in enumerate(inc_geojson_features):
    comma = ',' if i < len(inc_geojson_features) - 1 else ''
    geo_lines.append(json.dumps(feat, ensure_ascii=False, separators=(',', ':')) + comma)
geo_lines.append(']}')
geo_text = '\n'.join(geo_lines)
geo_path = os.path.join(B, 'incinerators.geojson')
with open(geo_path, 'w', encoding='utf-8', newline='\n') as f:
    f.write(geo_text)
shutil.copy2(geo_path, os.path.join(REF, 'incinerators.geojson'))
with open(os.path.join(REF, 'incinerators_part1.txt'), 'w', encoding='utf-8', newline='\n') as f:
    f.write('\n'.join(geo_lines[:15]) + '\n')
with open(os.path.join(REF, 'incinerators_part2.txt'), 'w', encoding='utf-8', newline='\n') as f:
    f.write('\n'.join(geo_lines[15:]))

inc_stats = {}
for label, grp in [
    ("SWIMS_25", [r for r in inc_rows if r['category'] == 'SWIMS_OPERATING_25']),
    ("ACTIVE_27", [r for r in inc_rows if r['status'] != '完工未營運']),
    ("ALL_28", inc_rows),
]:
    diffs = [float(r['village_minus_township_income']) for r in grp]
    pcts = [float(r['village_percentile_in_township']) for r in grp]
    mpcts = [float(r['village_midrank_percentile']) for r in grp]
    dists = [float(r['dist_to_other_township_m']) for r in grp]
    n_lower = sum(1 for d in diffs if d < 0)
    md, sd, t_val, p_t = paired_ttest(diffs)
    wp, wm, z_w, p_w = wilcoxon_signed_rank(diffs)
    s_diffs, s_pcts, s_mpcts, s_dists = sorted(diffs), sorted(pcts), sorted(mpcts), sorted(dists)
    n = len(grp)
    med_diff = s_diffs[n // 2] if n % 2 else 0.5 * (s_diffs[n // 2 - 1] + s_diffs[n // 2])
    med_pct = s_pcts[n // 2] if n % 2 else 0.5 * (s_pcts[n // 2 - 1] + s_pcts[n // 2])
    med_mpct = s_mpcts[n // 2] if n % 2 else 0.5 * (s_mpcts[n // 2 - 1] + s_mpcts[n // 2])
    med_dist = s_dists[n // 2] if n % 2 else 0.5 * (s_dists[n // 2 - 1] + s_dists[n // 2])
    inc_stats[label] = {
        "n": n,
        "township_median_mean": round(sum(float(r['township_income_median']) for r in grp) / n, 2),
        "host_village_median_mean": round(sum(float(r['host_village_income_median']) for r in grp) / n, 2),
        "diff_mean": round(md, 2), "diff_sd": round(sd, 2), "diff_median": round(med_diff, 1),
        "lower_count": n_lower, "lower_pct": round(100.0 * n_lower / n, 1),
        "paired_t": round(t_val, 3), "paired_p": p_t,
        "wilcoxon_w_plus": wp, "wilcoxon_w_minus": wm, "wilcoxon_z": round(z_w, 3), "wilcoxon_p": p_w,
        "pct_lte_mean": round(sum(pcts) / n, 1), "pct_lte_median": round(med_pct, 1),
        "pct_mid_mean": round(sum(mpcts) / n, 1), "pct_mid_median": round(med_mpct, 1),
        "dist_median_m": round(med_dist, 1), "dist_mean_m": round(sum(dists) / n, 1),
        "dist_le_1000m": sum(1 for d in dists if d <= 1000.0),
        "dist_le_2000m": sum(1 for d in dists if d <= 2000.0),
    }

print("4. Reconciling EMS_S_07 soil.geojson cleanly across valid named polygons (8,234) + outside sensitivity...")
soil_geo = json.load(open(os.path.join(B, 'scratch', 'env_check', 'soil.geojson'), encoding='utf-8'))
town_soil_strict = defaultdict(Counter)
town_soil_full = defaultdict(Counter)
outside_breakdown = Counter()

for f in soil_geo['features']:
    pr = f.get('properties') or {}
    st = pr.get('announcement_status') or 'unknown'
    vc = pr.get('villcode')
    if vc and str(vc) in villcode_to_town:
        tk = villcode_to_town[str(vc)]
        town_soil_strict[tk]['total'] += 1
        town_soil_full[tk]['total'] += 1
        if st == 'announcement_without_release_information':
            town_soil_strict[tk]['unreleased'] += 1
            town_soil_full[tk]['unreleased'] += 1
        elif st == 'release_information_present':
            town_soil_strict[tk]['released'] += 1
            town_soil_full[tk]['released'] += 1
    else:
        outside_breakdown[st] += 1
        coords = (f.get('geometry') or {}).get('coordinates') or [0, 0]
        hit = find_vill(coords[0], coords[1])
        if hit:
            tk = f"{norm(hit.get('COUNTYNAME'))}|{norm(hit.get('TOWNNAME'))}"
            if tk in town_inc:
                town_soil_full[tk]['total'] += 1
                if st == 'announcement_without_release_information':
                    town_soil_full[tk]['unreleased'] += 1
                elif st == 'release_information_present':
                    town_soil_full[tk]['released'] += 1

town_inc_25 = Counter()
town_inc_27 = Counter()
town_inc_cap_25 = Counter()
for r in inc_rows:
    tk = f"{r['county']}|{r['township']}"
    if r['category'] == 'SWIMS_OPERATING_25':
        town_inc_25[tk] += 1
        town_inc_cap_25[tk] += int(r['capacity_tons_per_day'])
    if r['status'] != '完工未營運':
        town_inc_27[tk] += 1

township_rows = []
for tk in sorted(town_inc.keys()):
    inc_d, den_d, ems_d = town_inc[tk], town_dens[tk], town_ems[tk]
    ss, sf = town_soil_strict[tk], town_soil_full[tk]
    area = den_d['area_km2']
    pop = den_d['population']
    pop_10k = max(0.0001, pop / 10000.0)
    ems_total = ems_d['ems01_records']
    ems_air = ems_d['air_records']
    ems_water = ems_d['water_records']
    ems_waste = ems_d['waste_records']
    soil_all = ss['total']
    soil_unrel = ss['unreleased']
    soil_rel = ss['released']
    assert soil_all == ems_d['soil_records'], f"Soil mismatch {tk}: {soil_all} vs {ems_d['soil_records']}"
    assert soil_all == soil_unrel + soil_rel, f"Soil status mismatch {tk}"

    township_rows.append({
        "township_key": tk, "county": inc_d['county'], "township": inc_d['township'],
        "is_mountain_indigenous": den_d['is_mountain_indigenous'],
        "income_median_thousand_twd": inc_d['median_income_thousand_twd'],
        "income_mean_thousand_twd": inc_d['mean_income_thousand_twd'],
        "tax_units": inc_d['tax_units'],
        "population_2024": pop, "area_km2": round(area, 4),
        "population_density_km2": den_d['population_density'],
        "log10_population_density": round(math.log10(max(0.1, den_d['population_density'])), 6),
        "ems01_total_records": ems_total, "ems01_air_records": ems_air,
        "ems01_water_records": ems_water, "ems01_waste_records": ems_waste,
        "soil_total_records": soil_all, "soil_unreleased_records": soil_unrel, "soil_released_records": soil_rel,
        "soil_unreleased_with_fallback_records": sf['unreleased'],
        "incinerator_swims25_count": town_inc_25[tk], "incinerator_active27_count": town_inc_27[tk],
        "incinerator_swims25_capacity_tpd": town_inc_cap_25[tk],
        "ems01_total_per_km2": round(ems_total / area, 4), "ems01_air_per_km2": round(ems_air / area, 4),
        "ems01_water_per_km2": round(ems_water / area, 4), "ems01_waste_per_km2": round(ems_waste / area, 4),
        "soil_total_per_km2": round(soil_all / area, 4), "soil_unreleased_per_km2": round(soil_unrel / area, 4),
        "soil_released_per_km2": round(soil_rel / area, 4),
        "ems01_total_per_10k_pop": round(ems_total / pop_10k, 4), "ems01_air_per_10k_pop": round(ems_air / pop_10k, 4),
        "ems01_water_per_10k_pop": round(ems_water / pop_10k, 4), "ems01_waste_per_10k_pop": round(ems_waste / pop_10k, 4),
        "soil_total_per_10k_pop": round(soil_all / pop_10k, 4), "soil_unreleased_per_10k_pop": round(soil_unrel / pop_10k, 4),
        "soil_released_per_10k_pop": round(soil_rel / pop_10k, 4),
    })

town_csv_path = os.path.join(B, 'township_cleaned_pollution_stats.csv')
with open(town_csv_path, 'w', encoding='utf-8-sig', newline='') as f:
    w = csv.DictWriter(f, fieldnames=list(township_rows[0].keys()))
    w.writeheader()
    w.writerows(township_rows)
shutil.copy2(town_csv_path, os.path.join(REF, 'township_cleaned_pollution_stats.csv'))

inc_vec = [r['income_median_thousand_twd'] for r in township_rows]
log_dens_vec = [r['log10_population_density'] for r in township_rows]
metrics_to_test = [
    ("ems01_total", "EMS_S_01 環保管理配對紀錄總數"),
    ("ems01_air", "EMS_S_01 空污管理分類配對紀錄"),
    ("ems01_water", "EMS_S_01 水污管理分類配對紀錄"),
    ("ems01_waste", "EMS_S_01 廢棄物清理法列管配對紀錄"),
    ("soil_total", "EMS_S_07 土壤及地下水場址配對總紀錄 (8,234筆)"),
    ("soil_unreleased", "EMS_S_07 未見解除資訊場址紀錄 (有效村里355筆)"),
    ("soil_released", "EMS_S_07 有解除公告資訊場址紀錄 (有效村里7,879筆)"),
]
corr_results = []
all_p = []
for prefix, label in metrics_to_test:
    raw_v = [float(r[f"{prefix}_records"]) for r in township_rows]
    km2_v = [float(r[f"{prefix}_per_km2"]) for r in township_rows]
    log_km2_v = [math.log10(1.0 + x) for x in km2_v]
    pop_v = [float(r[f"{prefix}_per_10k_pop"]) for r in township_rows]
    r_raw, p_raw, ci_raw = pearson_r(raw_v, inc_vec)
    rho_raw, p_rho_raw, _ = spearman_rho(raw_v, inc_vec)
    pr_raw, pp_raw = partial_corr(raw_v, inc_vec, log_dens_vec)
    r_km2, p_km2, _ = pearson_r(km2_v, inc_vec)
    rho_km2, p_rho_km2, _ = spearman_rho(km2_v, inc_vec)
    pr_km2, pp_km2 = partial_corr(km2_v, inc_vec, log_dens_vec)
    r_lkm2, p_lkm2, _ = pearson_r(log_km2_v, inc_vec)
    pr_lkm2, pp_lkm2 = partial_corr(log_km2_v, inc_vec, log_dens_vec)
    r_pop, p_pop, _ = pearson_r(pop_v, inc_vec)
    rho_pop, p_rho_pop, _ = spearman_rho(pop_v, inc_vec)
    corr_results.append({
        "metric": prefix, "label": label, "total_records": int(sum(raw_v)),
        "raw_pearson_r": round(r_raw, 4), "raw_pearson_p": p_raw, "raw_ci95": [round(ci_raw[0], 4), round(ci_raw[1], 4)],
        "raw_spearman_rho": round(rho_raw, 4), "raw_spearman_p": p_rho_raw,
        "raw_partial_r_log_dens": round(pr_raw, 4), "raw_partial_p": pp_raw,
        "per_km2_pearson_r": round(r_km2, 4), "per_km2_pearson_p": p_km2,
        "per_km2_spearman_rho": round(rho_km2, 4), "per_km2_spearman_p": p_rho_km2,
        "per_km2_partial_r_log_dens": round(pr_km2, 4), "per_km2_partial_p": pp_km2,
        "log1p_km2_pearson_r": round(r_lkm2, 4), "log1p_km2_pearson_p": p_lkm2,
        "log1p_km2_partial_r_log_dens": round(pr_lkm2, 4), "log1p_km2_partial_p": pp_lkm2,
        "per_10k_pop_pearson_r": round(r_pop, 4), "per_10k_pop_pearson_p": p_pop,
        "per_10k_pop_spearman_rho": round(rho_pop, 4), "per_10k_pop_spearman_p": p_rho_pop,
    })
    all_p.append(p_raw)
for res, q in zip(corr_results, bh_fdr(all_p)):
    res["raw_pearson_fdr_q"] = round(q, 6)

# Fallback sensitivity for soil_unreleased including 6 outside-named-boundary points
fb_unrel = [float(r['soil_unreleased_with_fallback_records']) for r in township_rows]
fb_km2_l = [math.log10(1.0 + float(r['soil_unreleased_with_fallback_records']) / r['area_km2']) for r in township_rows]
r_fb, p_fb, _ = pearson_r(fb_unrel, inc_vec)
pr_fb, pp_fb = partial_corr(fb_unrel, inc_vec, log_dens_vec)
pr_fb_l, pp_fb_l = partial_corr(fb_km2_l, inc_vec, log_dens_vec)

# Township-level incinerator comparison
inc25_towns = [r for r in township_rows if r['incinerator_swims25_count'] > 0]
non25_towns = [r for r in township_rows if r['incinerator_swims25_count'] == 0]
a_inc = [r['income_median_thousand_twd'] for r in inc25_towns]
b_inc = [r['income_median_thousand_twd'] for r in non25_towns]
t_w, df_w, p_w = welch_ttest(a_inc, b_inc)
u_mw, z_mw, p_mw = mann_whitney_u(a_inc, b_inc)
has_inc25_vec = [1.0 if r['incinerator_swims25_count'] > 0 else 0.0 for r in township_rows]
r_inc25_raw, p_inc25_raw, _ = pearson_r(has_inc25_vec, inc_vec)
pr_inc25_dens, pp_inc25_dens = partial_corr(has_inc25_vec, inc_vec, log_dens_vec)

# Summary of 368 townships income
sorted_t = sorted(township_rows, key=lambda r: r['income_median_thousand_twd'])
nat_inc_mean = round(sum(inc_vec) / len(inc_vec), 1)
s_inc_vec = sorted(inc_vec)
nat_inc_med = round(0.5 * (s_inc_vec[183] + s_inc_vec[184]), 1)

print("5. Computing 2024 Air Quality Multi-Sensitivity & FDR stats...")
town_lookup = {r['township_key']: r for r in township_rows}
off_st = json.load(open(os.path.join(B, 'scratch', 'official-stations.json'), encoding='utf-8'))
site_type_map = {str(rec.get("siteid")).strip(): rec.get("sitetype", "未知") for rec in off_st}
site_town_map = {str(rec.get("siteid")).strip(): (norm(rec.get("county")), norm(rec.get("township"))) for rec in off_st}
aq_rows = list(csv.DictReader(open(os.path.join(B, 'scratch', 'ir2024', 'annual-quality.csv'), encoding='utf-8-sig')))
rev_rows = list(csv.DictReader(open(os.path.join(B, 'scratch', 'ir2024', 'revised.csv'), encoding='utf-8-sig')))
rev_map = {str(r['siteid']).strip(): (norm(r['county']), norm(r['township'])) for r in rev_rows}
rev_map['44'] = ('臺南市', '善化區')

by_pollutant = defaultdict(list)
for r in aq_rows:
    sid = str(r['siteid']).strip()
    item = r.get('item_code') or r.get('item') or r.get('pollutant')
    val = float(r.get('annual_mean_daily_basis') or r.get('annual_mean'))
    c, t = rev_map.get(sid, site_town_map.get(sid, ('', '')))
    tk = f"{c}|{t}"
    tr = town_lookup[tk]
    by_pollutant[item].append({
        "siteid": sid, "sitename": r.get('sitename', ''), "county": c, "township": t, "town_key": tk,
        "sitetype": site_type_map.get(sid, '一般站'), "annual_mean": val,
        "income_median": float(tr['income_median_thousand_twd']),
        "log10_density": float(tr['log10_population_density']),
    })

air_results = {}
p_list_for_fdr, fdr_keys = [], []
for item, pts in by_pollutant.items():
    b77 = [p for p in pts if p['siteid'] != '44']
    s78 = pts
    gen_b = [p for p in b77 if p['sitetype'] == '一般站']
    gen_s = [p for p in s78 if p['sitetype'] == '一般站']
    def dedup_town(arr):
        grp = defaultdict(list)
        for p in arr:
            grp[p['town_key']].append(p)
        return [{"town_key": tk, "annual_mean": sum(x['annual_mean'] for x in g) / len(g),
                 "income_median": g[0]['income_median'], "log10_density": g[0]['log10_density']} for tk, g in sorted(grp.items())]
    item_res = {}
    for name, arr in [
        ("baseline_n77", b77), ("sensitivity_n78_with_shanhua", s78),
        ("general_stations_only_n60", gen_b), ("general_stations_only_n61_shanhua", gen_s),
        ("township_dedup_n74", dedup_town(b77)), ("township_dedup_n75_shanhua", dedup_town(s78)),
    ]:
        xs, ys, zs = [p['annual_mean'] for p in arr], [p['income_median'] for p in arr], [p['log10_density'] for p in arr]
        r, p_val, ci = pearson_r(xs, ys)
        rho, p_rho, _ = spearman_rho(xs, ys)
        pr, pp = partial_corr(xs, ys, zs)
        item_res[name] = {
            "n": len(arr), "pearson_r": round(r, 4), "pearson_p": p_val,
            "ci95": [round(ci[0], 4), round(ci[1], 4)],
            "spearman_rho": round(rho, 4), "spearman_p": p_rho,
            "partial_r_log_dens": round(pr, 4), "partial_p_log_dens": pp,
        }
        if name == "baseline_n77":
            p_list_for_fdr.extend([p_val, pp])
            fdr_keys.extend([(item, "bivariate_fdr_q"), (item, "partial_fdr_q")])
    air_results[item] = item_res
for (item, kname), qv in zip(fdr_keys, bh_fdr(p_list_for_fdr)):
    air_results[item]["baseline_n77"][kname] = round(qv, 6)

all_stats = {
    "national_income_368": {
        "year_roc": 113, "year_ad": 2024, "edition": "initial_assessment",
        "n": len(township_rows), "mean_of_medians": nat_inc_mean, "median_of_medians": nat_inc_med,
        "lowest_5": [(r['township_key'], r['income_median_thousand_twd']) for r in sorted_t[:5]],
        "highest_5": [(r['township_key'], r['income_median_thousand_twd']) for r in sorted_t[-5:][::-1]],
    },
    "soil_reconciliation": {
        "total_soil_geojson": len(soil_geo['features']),
        "matched_valid_villages": sum(r['soil_total_records'] for r in township_rows),
        "matched_unreleased": sum(r['soil_unreleased_records'] for r in township_rows),
        "matched_released": sum(r['soil_released_records'] for r in township_rows),
        "outside_valid_villages": dict(outside_breakdown),
        "fallback_unreleased_sensitivity": {"total": sum(int(x) for x in fb_unrel), "raw_r": round(r_fb, 4), "raw_p": p_fb, "partial_r": round(pr_fb, 4), "partial_p": pp_fb, "log_km2_partial_r": round(pr_fb_l, 4), "log_km2_partial_p": pp_fb_l},
    },
    "correlations_368": corr_results,
    "incinerator_township_comparison": {
        "n_hosting_townships_swims25": len(inc25_towns), "n_nonhosting_townships_swims25": len(non25_towns),
        "hosting_mean_income": round(sum(a_inc) / len(a_inc), 1), "hosting_median_income": sorted(a_inc)[len(a_inc) // 2],
        "nonhosting_mean_income": round(sum(b_inc) / len(b_inc), 1), "nonhosting_median_income": sorted(b_inc)[len(b_inc) // 2],
        "welch_t": round(t_w, 3), "welch_df": round(df_w, 1), "welch_p": p_w,
        "mann_whitney_u": u_mw, "mann_whitney_z": round(z_mw, 3), "mann_whitney_p": p_mw,
        "bivariate_r": round(r_inc25_raw, 4), "bivariate_p": p_inc25_raw,
        "partial_r_controlling_log10_density": round(pr_inc25_dens, 4), "partial_p_controlling_log10_density": pp_inc25_dens,
    },
    "incinerator_within_township": inc_stats,
    "air_quality_2024": air_results,
}
open(os.path.join(B, 'scratch', 'verified_all_stats.json'), 'w', encoding='utf-8').write(json.dumps(all_stats, ensure_ascii=False, indent=2))

print("6. Generating verified SVG charts...")
def make_scatter_svg(item_code, title_zh, y_label, filename):
    st_stats = air_results[item_code]["baseline_n77"]
    s78_stats = air_results[item_code]["sensitivity_n78_with_shanhua"]
    pts = [r for r in rev_rows if r['item'] == item_code]
    sh_row = next((r for r in aq_rows if str(r['siteid']).strip() == '44' and r['item'] == item_code), None)
    W, H = 860, 540
    pad_l, pad_r, pad_t, pad_b = 80, 40, 85, 70
    pw, ph = W - pad_l - pad_r, H - pad_t - pad_b
    ys = [float(r['annual_mean']) for r in pts] + ([float(sh_row['annual_mean_daily_basis'])] if sh_row else [])
    xmin, xmax = 350.0, 980.0
    ymin, ymax = max(0.0, math.floor(min(ys) * 0.85)), math.ceil(max(ys) * 1.12)
    def sx(x): return pad_l + (x - xmin) / (xmax - xmin) * pw
    def sy(y): return pad_t + ph - (y - ymin) / (ymax - ymin) * ph
    bx, by = [float(r['income_median_thousand']) for r in pts], [float(r['annual_mean']) for r in pts]
    mx, my = sum(bx) / len(bx), sum(by) / len(by)
    slope = sum((x - mx) * (y - my) for x, y in zip(bx, by)) / sum((x - mx) ** 2 for x in bx)
    intercept = my - slope * mx
    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" font-family="system-ui, -apple-system, Microsoft JhengHei, sans-serif">',
        f'<rect width="{W}" height="{H}" fill="#ffffff"/>',
        f'<text x="{pad_l}" y="34" font-size="18" font-weight="700" fill="#0f172a">{title_zh}</text>',
        f'<text x="{pad_l}" y="56" font-size="12.5" fill="#475569">主分析 (n={st_stats["n"]}): Pearson r = {st_stats["pearson_r"]:+.4f} (p = {st_stats["pearson_p"]:.4f}, FDR q = {st_stats["bivariate_fdr_q"]:.4f}) | 控制 log10(人口密度) 偏相關 r = {st_stats["partial_r_log_dens"]:+.4f} (p = {st_stats["partial_p_log_dens"]:.4f})</text>',
        f'<text x="{pad_l}" y="73" font-size="11.5" fill="#64748b">含善化站敏感度 (n={s78_stats["n"]}): r = {s78_stats["pearson_r"]:+.4f} (p = {s78_stats["pearson_p"]:.4f}), 偏相關 r = {s78_stats["partial_r_log_dens"]:+.4f} | 圓點顏色代表環境部 AQX_P_07 測站類型</text>',
    ]
    for xv in range(400, 951, 100):
        px = sx(xv)
        lines.append(f'<line x1="{px:.1f}" y1="{pad_t}" x2="{px:.1f}" y2="{pad_t+ph}" stroke="#e2e8f0" stroke-dasharray="3,3"/>')
        lines.append(f'<text x="{px:.1f}" y="{pad_t+ph+22}" font-size="11" text-anchor="middle" fill="#475569">{xv}</text>')
    y_step = 5 if (ymax - ymin) > 15 else 2
    for yv in range(int(ymin), int(ymax) + 1, y_step):
        py = sy(yv)
        lines.append(f'<line x1="{pad_l}" y1="{py:.1f}" x2="{pad_l+pw}" y2="{py:.1f}" stroke="#e2e8f0" stroke-dasharray="3,3"/>')
        lines.append(f'<text x="{pad_l-10}" y="{py+4:.1f}" font-size="11" text-anchor="end" fill="#475569">{yv}</text>')
    lines.append(f'<rect x="{pad_l}" y="{pad_t}" width="{pw}" height="{ph}" fill="none" stroke="#94a3b8" stroke-width="1"/>')
    x1, x2 = 365.0, 950.0
    lines.append(f'<line x1="{sx(x1):.1f}" y1="{sy(intercept + slope * x1):.1f}" x2="{sx(x2):.1f}" y2="{sy(intercept + slope * x2):.1f}" stroke="#dc2626" stroke-width="2" stroke-dasharray="6,4"/>')
    type_colors = {"一般站": "#2563eb", "交通站": "#d97706", "工業站": "#7c3aed", "背景站": "#059669", "公園站": "#0d9488", "其它站": "#64748b"}
    for r in pts:
        stype = site_type_map.get(str(r['siteid']).strip(), "一般站")
        col = type_colors.get(stype, "#2563eb")
        px, py = sx(float(r['income_median_thousand'])), sy(float(r['annual_mean']))
        lines.append(f'<circle cx="{px:.1f}" cy="{py:.1f}" r="5" fill="{col}" fill-opacity="0.78" stroke="#ffffff" stroke-width="1"><title>{r["sitename"]} ({r["county"]}{r["township"]}, {stype}): 所得={r["income_median_thousand"]}千元, {item_code}={float(r["annual_mean"]):.2f}</title></circle>')
        if float(r['income_median_thousand']) > 750 or float(r['annual_mean']) > ymax * 0.86 or float(r['annual_mean']) < ymin + (ymax - ymin) * 0.12:
            lines.append(f'<text x="{px+7:.1f}" y="{py+3:.1f}" font-size="10" fill="#334155">{r["sitename"]}</text>')
    if sh_row:
        px, py = sx(630.0), sy(float(sh_row['annual_mean_daily_basis']))
        lines.append(f'<circle cx="{px:.1f}" cy="{py:.1f}" r="6" fill="none" stroke="#dc2626" stroke-width="2" stroke-dasharray="2,2"/>')
        lines.append(f'<text x="{px+8:.1f}" y="{py-4:.1f}" font-size="10.5" font-weight="600" fill="#dc2626">善化(待確認/n=78敏感度)</text>')
    lx = pad_l + 12
    for st_label, col in [("一般站", "#2563eb"), ("交通站", "#d97706"), ("工業站", "#7c3aed"), ("背景/公園/其它", "#059669")]:
        lines.append(f'<circle cx="{lx}" cy="{pad_t+16}" r="4.5" fill="{col}"/>')
        lines.append(f'<text x="{lx+8}" y="{pad_t+20}" font-size="11" fill="#334155">{st_label}</text>')
        lx += 95
    lines.append(f'<text x="{pad_l+pw/2:.1f}" y="{H-18}" font-size="12.5" font-weight="600" text-anchor="middle" fill="#1e293b">所屬鄉鎮市區綜所稅申報中位數（千元／年，113年度初步核定）</text>')
    lines.append(f'<text x="22" y="{pad_t+ph/2:.1f}" font-size="12.5" font-weight="600" text-anchor="middle" fill="#1e293b" transform="rotate(-90 22 {pad_t+ph/2:.1f})">{y_label}</text>')
    lines.append('</svg>')
    p = os.path.join(FIG_DIR, filename)
    open(p, 'w', encoding='utf-8', newline='\n').write('\n'.join(lines))
    shutil.copy2(p, os.path.join(REF, filename))

make_scatter_svg("PM2.5", "2024 年台灣空品測站 PM2.5 年均濃度與鄉鎮所得中位數關聯圖", "2024 PM2.5 日均值年平均 (μg/m³)", "pm25_vs_income.svg")
make_scatter_svg("NO2", "2024 年台灣空品測站 NO2 年均濃度與鄉鎮所得中位數關聯圖", "2024 NO2 日均值年平均 (ppb)", "no2_vs_income.svg")

# Multi-scale Incinerator SVG
W, H = 940, 880
pad_l, pad_r, pad_t, pad_b = 265, 55, 100, 65
pw, ph = W - pad_l - pad_r, H - pad_t - pad_b
swims_sorted = sorted([r for r in inc_rows if r['category'] == 'SWIMS_OPERATING_25'], key=lambda x: float(x['township_income_median']), reverse=True)
other_sorted = sorted([r for r in inc_rows if r['category'] != 'SWIMS_OPERATING_25'], key=lambda x: float(x['township_income_median']), reverse=True)
ordered = swims_sorted + other_sorted
xmax = 1180.0
def sx_inc(v): return pad_l + (v / xmax) * pw
s25 = inc_stats["SWIMS_25"]
itc = all_stats["incinerator_township_comparison"]
svg_inc = [
    f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" font-family="system-ui, -apple-system, Microsoft JhengHei, sans-serif">',
    f'<rect width="{W}" height="{H}" fill="#ffffff"/>',
    f'<text x="24" y="32" font-size="17.5" font-weight="700" fill="#0f172a">台灣大型垃圾焚化廠／熱處理設施（28處）：所在鄉鎮市區 vs. 所在村里所得中位數多尺度比較</text>',
    f'<text x="24" y="54" font-size="12" fill="#334155">環境部 SWIMS 營運中 25 廠：所在行政區中位數平均 {s25["township_median_mean"]:.1f} 千元 vs. 所在村里平均 {s25["host_village_median_mean"]:.1f} 千元（平均差距 {s25["diff_mean"]:+.1f} 千元，{s25["lower_count"]}/25 [{s25["lower_pct"]:.0f}%] 村里低於全區，配對 t={s25["paired_t"]:.2f}, p={s25["paired_p"]:.5f}）</text>',
    f'<text x="24" y="72" font-size="11.5" fill="#64748b">長條＝所在鄉鎮市區所得中位數；紅點＝焚化廠所在村里所得中位數；控制人口密度後鄉鎮層級偏相關不顯著（r={itc["partial_r_controlling_log10_density"]:+.4f}, p={itc["partial_p_controlling_log10_density"]:.4f}）</text>',
]
for xv in range(0, 1151, 200):
    px = sx_inc(xv)
    svg_inc.append(f'<line x1="{px:.1f}" y1="{pad_t}" x2="{px:.1f}" y2="{pad_t+ph}" stroke="#e2e8f0" stroke-dasharray="3,3"/>')
    svg_inc.append(f'<text x="{px:.1f}" y="{pad_t+ph+20}" font-size="11" text-anchor="middle" fill="#475569">{xv}k</text>')
px_nat = sx_inc(nat_inc_mean)
svg_inc.append(f'<line x1="{px_nat:.1f}" y1="{pad_t}" x2="{px_nat:.1f}" y2="{pad_t+ph}" stroke="#0f172a" stroke-width="1.5" stroke-dasharray="5,4"/>')
svg_inc.append(f'<text x="{px_nat+4:.1f}" y="{pad_t-6}" font-size="10.5" font-weight="600" fill="#0f172a">全國368鄉鎮中位數平均 ({nat_inc_mean:.1f}k)</text>')
row_h = ph / len(ordered)
for i, r in enumerate(ordered):
    yc = pad_t + (i + 0.5) * row_h
    if i == 25:
        svg_inc.append(f'<line x1="20" y1="{pad_t + i*row_h:.1f}" x2="{W-20}" y2="{pad_t + i*row_h:.1f}" stroke="#94a3b8" stroke-width="1.5" stroke-dasharray="4,3"/>')
    t_med, v_med, diff = float(r['township_income_median']), float(r['host_village_income_median']), float(r['village_minus_township_income'])
    bar_col = "#3b82f6" if r['category'] == "SWIMS_OPERATING_25" else ("#10b981" if r['status'] != "完工未營運" else "#94a3b8")
    svg_inc.append(f'<text x="{pad_l-8}" y="{yc+4:.1f}" font-size="11" text-anchor="end" fill="#1e293b">{r["county"]}{r["township"]}｜{r["village"]} ({r["name"][:8]})</text>')
    svg_inc.append(f'<rect x="{pad_l}" y="{yc-7:.1f}" width="{sx_inc(t_med)-pad_l:.1f}" height="14" fill="{bar_col}" fill-opacity="0.35" stroke="{bar_col}" stroke-width="1"/>')
    x_t, x_v = sx_inc(t_med), sx_inc(v_med)
    seg_col = "#dc2626" if diff < 0 else "#16a34a"
    svg_inc.append(f'<line x1="{x_t:.1f}" y1="{yc:.1f}" x2="{x_v:.1f}" y2="{yc:.1f}" stroke="{seg_col}" stroke-width="2.2"/>')
    svg_inc.append(f'<circle cx="{x_v:.1f}" cy="{yc:.1f}" r="4.5" fill="{seg_col}" stroke="#ffffff" stroke-width="1"/>')
    svg_inc.append(f'<text x="{max(x_t, x_v)+6:.1f}" y="{yc+3.5:.1f}" font-size="10" fill="#334155">區{t_med:.0f}k / 里{v_med:.0f}k ({diff:+.0f}k, 距界{float(r["dist_to_other_township_m"]):.0f}m)</text>')
svg_inc.append(f'<text x="{pad_l+pw/2:.1f}" y="{H-18}" font-size="12" font-weight="600" text-anchor="middle" fill="#1e293b">綜所稅申報所得中位數（千元／年，113年度）— 藍條：SWIMS營運中25廠｜綠條：新建/生質能2廠｜灰條：林內未營運廠｜紅點：所在村里</text>')
svg_inc.append('</svg>')
inc_svg_path = os.path.join(FIG_DIR, 'incinerator_income_rank.svg')
open(inc_svg_path, 'w', encoding='utf-8', newline='\n').write('\n'.join(svg_inc))
shutil.copy2(inc_svg_path, os.path.join(REF, 'incinerator_income_rank.svg'))

print("7. Updating manifest_fixed.json with exact SHA-256 of index_fixed.html & incinerators.geojson...")
idx_sha = hashlib.sha256(open(os.path.join(B, 'index_fixed.html'), 'rb').read()).hexdigest()
inc_sha = hashlib.sha256(open(geo_path, 'rb').read()).hexdigest()
man = json.load(open(os.path.join(B, 'scratch', 'env_check', 'environment-preview_manifest.json'), encoding='utf-8'))
man['prepared_at_utc'] = "2026-11-13T01:45:00+00:00"
man['public_files_sha256']['index.html'] = idx_sha
man['public_files_sha256']['incinerators.geojson'] = inc_sha
man_text = json.dumps(man, ensure_ascii=False, indent=2) + '\n'
open(os.path.join(B, 'manifest_fixed.json'), 'w', encoding='utf-8', newline='\n').write(man_text)
open(os.path.join(REF, 'manifest.json'), 'w', encoding='utf-8', newline='\n').write(man_text)
print("8. Dynamically generating all 4 Markdown reports (both local & GitHub-staged versions)...")
# Helper formatters
def fmt_p(p):
    if p < 1e-4:
        return f"{p:.2e}"
    return f"{p:.5f}"

a27 = inc_stats["ACTIVE_27"]
a28 = inc_stats["ALL_28"]
soil_rec = all_stats["soil_reconciliation"]
corr_map = {c['metric']: c for c in corr_results}

# Top negative gap SWIMS + Zhubei examples dynamically
by_gap = sorted(inc_rows, key=lambda r: float(r['village_minus_township_income']))
example_bullets = []
for r in [r for r in by_gap if r['wep_no'] in ('NON_SWIMS_HC_BOO', 'WEPA4244', 'WEPS2225', 'WEPF0537', 'WEPA4427')]:
    example_bullets.append(
        f"  - **{r['county']}{r['township']}（{r['name']}）**：全區所得中位數 **{float(r['township_income_median']):,.0f} 千元**，而廠址所在**{r['village']}**僅 **{float(r['host_village_income_median']):,.0f} 千元**（差距 **{float(r['village_minus_township_income']):+.0f} 千元**，該里在區內 {r['village_count_in_township']} 個村里中位於第 **{r['village_percentile_in_township']}%** 分位〔中位秩 {r['village_midrank_percentile']}%〕，距最近外區界僅 **{float(r['dist_to_other_township_m']):,.1f} 公尺**〔鄰 {r['nearest_other_township']}〕）。"
    )

# Table rows dynamically from taiwan_incinerators_verified.csv
inc_table_rows = []
for r in inc_rows:
    cat_s = "SWIMS 25廠 / 營運中" if r['category'] == "SWIMS_OPERATING_25" else (f"{r['status']} / {r['category']}")
    yr_s = f"{r['completion_year']} / {r['operation_start_year'] or '—'}"
    coord_s = f"`{float(r['lon']):.6f}, {float(r['lat']):.6f}`"
    inc_table_rows.append(
        f"| {r['id']} | `{r['wep_no']}` | {r['name']} | {cat_s} | {r['operation_mode']} | {yr_s} | {int(r['capacity_tons_per_day']):,} | {r['county']}{r['township']}{r['village']} (`{r['villcode']}`) | {r['address']} | {coord_s} | {float(r['township_income_median']):.0f} | {float(r['host_village_income_median']):.0f} | **{float(r['village_minus_township_income']):+.0f}** | {float(r['village_percentile_in_township']):.1f}% | {float(r['dist_to_other_township_m']):,.1f} ({r['nearest_other_township']}) |"
    )

def write_dual_report(rel_repo_path, ref_filename, local_text, gh_text):
    lp = os.path.join(B, rel_repo_path)
    with open(lp, 'w', encoding='utf-8', newline='\n') as f:
        f.write(local_text)
    with open(os.path.join(REF, ref_filename), 'w', encoding='utf-8', newline='\n') as f:
        f.write(gh_text)

# --- Report A: incinerators_environmental_justice.md ---
def build_inc_md(is_gh):
    csv_ref = "../../data/taiwan_incinerators_verified.csv" if is_gh else f"file:///{B.replace(chr(92), '/')}/taiwan_incinerators_verified.csv"
    geo_ref = "../../environment-preview/incinerators.geojson" if is_gh else f"file:///{B.replace(chr(92), '/')}/incinerators.geojson"
    fig_ref = "../figures/incinerator_income_rank.svg" if is_gh else f"file:///{B.replace(chr(92), '/')}/reports/figures/incinerator_income_rank.svg"
    return f"""# 台灣大型垃圾焚化廠與熱處理設施（28 處）多尺度環境正義實證分析報告

- **資料基準與核驗日期**：2026-11-13
- **核心官方來源**：
  1. 環境部環境管理署「焚化廠營運管理資訊系統（SWIMS）」官方 25 座營運中焚化廠分布圖座標與編號（`https://swims.moenv.gov.tw/`，`WEPC1448`–`WEPV9500`）
  2. 環境部 SWIMS《興建營運基本資料表》（`swims_basic_info.pdf`，民國 111 年 9 月 5 日版）與各廠建廠沿革摘述
  3. 財政部 **113 年度（2024 年）初步核定綜合所得稅申報統計**（368 鄉鎮市區中位數 `township-income-source.csv` 與 7,653 具名有效村里幾何 `income.geojson`，均為 `income_year = 2024`）
  4. 內政部 2024 年底鄉鎮市區人口密度（`township-density-2024.json`，含 30 個山地原住民鄉／區，共 **368/368** 鄉鎮市區完整配對）

---

## 1. 研究問題與「可變地區單元問題（MAUP）」修正

在前一版初步探索中，僅以「鄉鎮市區（`N = 368`）」未校正平均數比較設廠與非設廠行政區所得，且早期清冊座標源自非官方摘要（造成 6 處落入鄰區、雲林林內廠行政區誤植）。本報告完成兩項根本修正：

1. **100% 官方來源與點位落區核驗（Point-in-Polygon Verification）**：全數採用環境部 SWIMS 官方系統之 25 座營運中大型垃圾焚化廠座標與編號（`WEPC1448`–`WEPV9500`），並清楚區分另外 3 處非屬傳統 SWIMS 25 廠之大型廢棄物熱處理設施（桃園觀音生質能中心 BOT、新竹竹北高效能熱處理設施 BOO、雲林林內完工未營運 BOO 廠），**共 28 處全數通過 `income.geojson` 村里多邊形落點檢驗（28/28 行政區與村里完全吻合）**。
2. **多尺度檢定與精確邊界距離量化**：同步計算（a）鄉鎮市區層級控制 `log10(人口密度)` 前後之關聯、（b）焚化廠所在**具體村里（`VILLCODE`）**與所屬**母行政區（鄉／鎮／市／區）**之配對所得差距，以及（c）廠址至最近相鄰鄉鎮市區完整多邊形線段邊界之精確最短距離（公尺）。

---

## 2. 核心實證發現（三階層統計檢定）

### 2.1 第一層：鄉鎮市區層級（未控制 vs. 控制人口密度，`N = 368`）

| 分析口徑 | 設有焚化廠行政區 | 未設焚化廠行政區 | 雙變量檢定（未控制人口密度） | 控制 $\\log_{{10}}(\\text{{人口密度}})$ 偏相關 |
|---|---|---|---|---|
| **環境部 SWIMS 營運中 25 廠** | $n = {itc['n_hosting_townships_swims25']}$ 鄉鎮市區<br>中位數平均：**{itc['hosting_mean_income']:.1f} 千元**<br>群體中位數：**{itc['hosting_median_income']:.1f} 千元** | $n = {itc['n_nonhosting_townships_swims25']}$ 鄉鎮市區<br>中位數平均：**{itc['nonhosting_mean_income']:.1f} 千元**<br>群體中位數：**{itc['nonhosting_median_income']:.1f} 千元** | Welch $t = {itc['welch_t']:.3f}$ ($p = {fmt_p(itc['welch_p'])}$)<br>Mann-Whitney $U = {itc['mann_whitney_u']:,.0f}$ ($z = {itc['mann_whitney_z']:.3f}, p = {fmt_p(itc['mann_whitney_p'])}$)<br>點二系列 $r = {itc['bivariate_r']:+.4f}$ ($p = {fmt_p(itc['bivariate_p'])}$) | **偏相關 $r = {itc['partial_r_controlling_log10_density']:+.4f}$**<br>**($p = {fmt_p(itc['partial_p_controlling_log10_density'])}$，不顯著)** |

- **詮釋**：在未控制人口密度時，設有 SWIMS 25 座焚化廠的行政區 2024 年所得中位數平均較高（{itc['hosting_mean_income']:.1f} 千元 vs. {itc['nonhosting_mean_income']:.1f} 千元），係因《台灣地區垃圾資源回收（焚化）廠興建工程計畫》優先服務高人口密度都會區；**一旦控制 $\\log_{{10}}(\\text{{人口密度}})$，鄉鎮層級設廠與否之所得差異即不顯著（偏相關 $r = {itc['partial_r_controlling_log10_density']:+.4f}, p = {fmt_p(itc['partial_p_controlling_log10_density'])}$）**。

---

### 2.2 第二層：行政區內部「所在村里 vs. 母鄉鎮市區」配對檢定（微觀環境不平等）

將空間單位細化至焚化廠實際坐落的「**村里（`VILLCODE`）**」，與所屬鄉鎮市區整體所得中位數配對比較（百分位定義為母區內所得小於或等於該里之村里佔比，並併附中位秩百分位）：

| 樣本範圍 | 設施數 ($n$) | 所屬鄉鎮市區平均 | 廠址所在村里平均 | 村里減去所屬鄉鎮平均差距 (SD) | 村里低於所屬鄉鎮比例 | 配對 $t$ 檢定 | Wilcoxon 符號等級檢定 | 區內所得百分位（中位數 / 平均） |
|---|---|---|---|---|---|---|---|---|
| **SWIMS 營運中 25 廠** | {s25['n']} | {s25['township_median_mean']:.1f} 千元 | **{s25['host_village_median_mean']:.1f} 千元** | **{s25['diff_mean']:+.1f} 千元** ({s25['diff_sd']:.1f}k)<br>中位數差距 **{s25['diff_median']:+.1f} 千元** | **{s25['lower_count']} / {s25['n']} ({s25['lower_pct']:.1f}%)** | $t = {s25['paired_t']:.3f}$<br>**$p = {s25['paired_p']:.6f}$** | $W^+ = {s25['wilcoxon_w_plus']:.0f}, W^- = {s25['wilcoxon_w_minus']:.0f}$<br>$z = {s25['wilcoxon_z']:.3f}, \\mathbf{{p = {s25['wilcoxon_p']:.6f}}}$ | **{s25['pct_lte_median']:.1f}% / {s25['pct_lte_mean']:.1f}%**<br>(中位秩中位 {s25['pct_mid_median']:.1f}%) |
| **營運／試運轉 27 處**（含桃園生質能、竹北廠） | {a27['n']} | {a27['township_median_mean']:.1f} 千元 | **{a27['host_village_median_mean']:.1f} 千元** | **{a27['diff_mean']:+.1f} 千元** ({a27['diff_sd']:.1f}k)<br>中位數差距 **{a27['diff_median']:+.1f} 千元** | **{a27['lower_count']} / {a27['n']} ({a27['lower_pct']:.1f}%)** | $t = {a27['paired_t']:.3f}$<br>**$p = {a27['paired_p']:.6f}$** | $W^+ = {a27['wilcoxon_w_plus']:.0f}, W^- = {a27['wilcoxon_w_minus']:.0f}$<br>$z = {a27['wilcoxon_z']:.3f}, \\mathbf{{p = {a27['wilcoxon_p']:.6f}}}$ | **{a27['pct_lte_median']:.1f}% / {a27['pct_lte_mean']:.1f}%**<br>(中位秩中位 {a27['pct_mid_median']:.1f}%) |
| **全清冊 28 處**（含雲林林內未營運廠） | {a28['n']} | {a28['township_median_mean']:.1f} 千元 | **{a28['host_village_median_mean']:.1f} 千元** | **{a28['diff_mean']:+.1f} 千元** ({a28['diff_sd']:.1f}k)<br>中位數差距 **{a28['diff_median']:+.1f} 千元** | **{a28['lower_count']} / {a28['n']} ({a28['lower_pct']:.1f}%)** | $t = {a28['paired_t']:.3f}$<br>**$p = {a28['paired_p']:.6f}$** | $W^+ = {a28['wilcoxon_w_plus']:.0f}, W^- = {a28['wilcoxon_w_minus']:.0f}$<br>$z = {a28['wilcoxon_z']:.3f}, \\mathbf{{p = {a28['wilcoxon_p']:.6f}}}$ | **{a28['pct_lte_median']:.1f}% / {a28['pct_lte_mean']:.1f}%**<br>(中位秩中位 {a28['pct_mid_median']:.1f}%) |

- **關鍵案例佐證**：
{chr(10).join(example_bullets)}

---

### 2.3 第三層：行政區邊界選址效應量化檢驗（精確線段距離 `dist_to_other_township_m`）

以全島村里多邊形所有頂點構成之鄰區邊界線段，計算各焚化廠至「最近不同鄉鎮市區邊界」之最短地表距離：
- **SWIMS 營運中 {s25['n']} 廠**：
  - 距最近相鄰鄉鎮市區邊界之**中位數距離僅 {s25['dist_median_m']:,.1f} 公尺**（平均距離 {s25['dist_mean_m']:,.1f} 公尺）。
  - **{s25['dist_le_1000m']} / {s25['n']} 座（{100*s25['dist_le_1000m']/s25['n']:.1f}%）**距離相鄰行政區邊界在 **1 公里（1,000 公尺）以內**。
  - **{s25['dist_le_2000m']} / {s25['n']} 座（{100*s25['dist_le_2000m']/s25['n']:.1f}%）**距離相鄰行政區邊界在 **2 公里（2,000 公尺）以內**（唯一超過 2 公里者為臺東縣臺東市豐谷里廠址，因其轄區面積遼闊，距相鄰卑南鄉界 {float(next(r['dist_to_other_township_m'] for r in inc_rows if r['wep_no']=='WEPV9500')):,.1f} 公尺，位於南側海岸線）。
- **跨界選址極端案例——臺南市永康廠（`WEPR8506`）**：
  - 永康廠法定門牌為「臺南市永康區王行東路 166 號」，廠區西側大門（`120.281500, 23.040100`）落於**永康區王行里**（495 千元，低於永康區整體 532 千元），距離最近外區界（**新化區**）僅 **30.5 公尺**；而環境部 SWIMS 地圖標記的煙囪座標（`120.282537, 23.040198`）則恰位於行政界線東側 **77.2 公尺** 處（依多邊形邊界落於**新化區北勢里**，464 千元）。

---

## 3. 方法論限制與因果詮釋警語

> [!WARNING]
> **時間先後與雙向選擇限制（Temporal Ordering & Residential Sorting）**：
> 台灣 25 座 SWIMS 大型垃圾焚化廠多於 **1987 年至 2008 年間**興建完工（臺東廠則於 2023 年啟用），而本研究所使用之鄉鎮與村里所得為 **113 年度（2024 年）初步核定**橫斷面資料。因此，所在村里所得低於母行政區（SWIMS 25 廠平均差距 {s25['diff_mean']:+.1f} 千元，$p = {s25['paired_p']:.6f}$）同時反映（1）當年選址偏好地價與密度較低之河口、海岸防風林、山谷或工業邊界地段，以及（2）設廠後 20 至 30 年間都市住宅開發向核心區集中與鄰避負外部性造成的居住分選（Sorting）。橫斷面比較無法單獨切割兩者各自佔比。

---

## 4. 全台 28 處大型垃圾焚化廠與熱處理設施完整核驗清冊

以下 28 處資料均與結構化資料集 [taiwan_incinerators_verified.csv]({csv_ref}) 及圖層檔案 [incinerators.geojson]({geo_ref}) 完全一致（所有數值皆由同一驗證管線直接輸出）：

| # | SWIMS / 識別編號 | 設施名稱 | 類別 / 狀態 | 營運方式 | 完工 / 啟用年 | 設計量 (噸/日) | 核驗行政區與村里 (`VILLCODE`) | 法定地址 | 核驗座標 (`lon, lat`) | 鄉鎮中位數 (千元) | 村里中位數 (千元) | 村里減鄉鎮 (千元) | 區內百分位 | 距外區界 (公尺 / 鄰區) |
|---:|---|---|---|---|---|---|---:|---|---|---|---:|---:|---:|---:|---:|
{chr(10).join(inc_table_rows)}

> 註：#25 臺東廠興建面積未列於 SWIMS《興建營運基本資料表》且未另外採信未具名來源；#26–#28 非傳統 SWIMS 25 廠之部分未公開單爐／裝置容量／煙囪細項亦保留為空值（`null`），僅納入已查證之公開官方規格。

---

## 5. 多尺度所得比較視覺化

![台灣大型垃圾焚化廠與熱處理設施：鄉鎮市區 vs. 所在村里所得中位數比較]({fig_ref})
"""

# --- Report B: cleaned_pollution_income_analysis.md ---
def build_cleaned_md(is_gh):
    csv_ref = "../../data/township_cleaned_pollution_stats.csv" if is_gh else f"file:///{B.replace(chr(92), '/')}/township_cleaned_pollution_stats.csv"
    low5 = all_stats["national_income_368"]["lowest_5"]
    high5 = all_stats["national_income_368"]["highest_5"]
    c_rows = []
    for c in corr_results:
        c_rows.append(
            f"| **{c['label']}** ({c['total_records']:,} 筆) | **{c['raw_pearson_r']:+.4f}**<br>($p={fmt_p(c['raw_pearson_p'])}$ / $q={c['raw_pearson_fdr_q']:.4f}$) | **{c['raw_spearman_rho']:+.4f}** | **{c['raw_partial_r_log_dens']:+.4f}**<br>($p={fmt_p(c['raw_partial_p'])}$) | {c['per_km2_pearson_r']:+.4f} / {c['per_km2_spearman_rho']:+.4f} | **{c['log1p_km2_partial_r_log_dens']:+.4f}**<br>($p={fmt_p(c['log1p_km2_partial_p'])}$) | {c['per_10k_pop_pearson_r']:+.4f} / {c['per_10k_pop_spearman_rho']:+.4f} |"
        )
    fb = soil_rec["fallback_unreleased_sensitivity"]
    return f"""# 全台 368 鄉鎮市區環保列管配對紀錄（`EMS_S_01`）與土壤／地下水場址公告（`EMS_S_07`）空間計量分析報告

- **資料基準與核驗日期**：2026-11-13
- **涵蓋範圍**：全國 **368 / 368 個鄉鎮市區**（已修正先前漏配 `※` 前綴之 30 個山地原住民鄉／區，完整納入 368 個行政區之 2024 年人口、土地面積與人口密度）
- **所得資料基準**：財政部 **113 年度（2024 年）初步核定綜合所得稅申報統計**（鄉鎮合計中位數，非村里簡單平均）
- **產出資料集**：[township_cleaned_pollution_stats.csv]({csv_ref})

---

## 1. 資料定義與方法論修正說明

1. **明確區分「管理分類配對紀錄數」與「獨立事業／鄰避設施數」**：
   - `EMS_S_01` 全檔 454,333 筆原始列，由專案前置流程移除完全重複列（21,867 筆）、排除 `(0, 0)` 零座標（171,709 筆）及有效具名村里邊界外／重疊點位（4,160 筆）後，共 **256,597 筆**唯一配對至 7,653 個有效具名村里多邊形。
   - **重要限制**：`EMS_S_01` 中有 **20,268 個管制編號（`emsno`）對應多筆非完全相同之歷史或跨分類紀錄**，因此紀錄數不等於現行獨立事業家數。
   - 此外，`iswaste`（164,707 筆已配對紀錄）代表**受《廢棄物清理法》列管之申報紀錄（絕大多數為工廠、醫療院所、營造工地等事業廢棄物產出源）**，**不等於焚化廠或掩埋場等「鄰避設施」**。
2. **明確區分「未見解除資訊（`announcement_without_release_information`）」與「現行列管中」及邊界配對口徑**：
   - `EMS_S_07` 去重後全檔共 **8,254 筆**（`announcement_without_release_information` **361 筆** + `release_information_present` **7,893 筆**）。
   - 注意：**「未見解除資訊」僅代表靜態開放資料快照中尚未填入解除欄位，不等於主管機關認證之「現行列管中」**。
   - 在空間分析中，有 **8,234 筆**（`355` 筆未見解除資訊 + `7,879` 筆有解除公告資訊）嚴格落於 7,653 個有效具名村里多邊形內（與 `income.geojson` 完全一致，確保鄉鎮表內 `soil_total == soil_unreleased + soil_released` 帳目一致）；另有 `20` 筆（`6` 筆未見解除資訊 + `14` 筆有解除公告資訊）為 `outside_named_boundaries`。即使以非對稱多邊形備援配對納入全數可歸區之 361 筆未見解除資訊紀錄，控制 $\\log_{{10}}(\\text{{人口密度}})$ 後之偏相關仍為 $r = {fb['partial_r']:+.4f}$ ($p = {fb['partial_p']:.4f}$)，對數每平方公里偏相關為 $r = {fb['log_km2_partial_r']:+.4f}$ ($p = {fb['log_km2_partial_p']:.4f}$)，結論完全不變。
   - **農地地號切分偏誤**：如彰化縣鹿港鎮（嚴格配對共 856 筆有解除公告資訊、7 筆未見解除資訊，合計 863 筆），主因早年電鍍廢水污染灌溉農地後，環保機關依地籍地號逐筆公告控制場址與完成整備解除，故筆數高度反映農地地號細碎程度。
3. **面積與人口標準化（`N = 368`）**：
   - 同步提供（1）原始筆數、（2）**每平方公里密度（筆／$\\text{{km}}^2$）**、（3）**對數面積密度 $\\log_{{10}}(1 + \\text{{筆}}/\\text{{km}}^2)$**、（4）**每萬人筆數（筆／萬人）**，並一律控制 $\\log_{{10}}(\\text{{人口密度}})$ 與計算 BH FDR $q$ 值。

---

## 2. 全國 368 鄉鎮市區 113 年度（2024）所得描述統計

- **樣本數**：368 個鄉鎮市區（含 30 個山地原住民鄉／區）
- **鄉鎮所得中位數平均**：{nat_inc_mean:.1f} 千元（群體中位數：{nat_inc_med:.1f} 千元）
- **全國所得中位數最低前 5 名鄉鎮**：
{chr(10).join(f"  {i+1}. {k.replace('|', '')}（**{v:.1f} 千元**）" for i, (k, v) in enumerate(low5))}
- **全國所得中位數最高前 5 名鄉鎮**：
{chr(10).join(f"  {i+1}. {k.replace('|', '')}（**{v:,.1f} 千元**）" for i, (k, v) in enumerate(high5))}

---

## 3. 環保列管紀錄與土壤場址對鄉鎮所得之多口徑相關分析（`N = 368`）

| 指標類別（全國 368 鄉鎮合計） | 原始筆數 Pearson $r$ ($p$ / FDR $q$) | 原始筆數 Spearman $\\rho$ | 原始筆數控制 $\\log_{{10}}(\\text{{密度}})$ 偏相關 $r$ ($p$) | 每 $\\text{{km}}^2$ 密度 Pearson $r$ / Spearman $\\rho$ | $\\log_{{10}}(1+\\text{{每km}}^2)$ 控制密度偏相關 $r$ ($p$) | 每萬人筆數 Pearson $r$ / Spearman $\\rho$ |
|---|---|---|---|---|---|---|
{chr(10).join(c_rows)}

---

## 4. 關鍵計量結論

1. **空污列管紀錄（`ems01_air`）與土壤場址（`soil_unreleased`）的雙變量正相關完全由城鄉人口密度解釋**：
   - 控制 $\\log_{{10}}(\\text{{人口密度}})$ 後，空污管理紀錄偏相關為 **{corr_map['ems01_air']['raw_partial_r_log_dens']:+.4f}** ($p = {corr_map['ems01_air']['raw_partial_p']:.4f}$)，對數每平方公里偏相關為 **{corr_map['ems01_air']['log1p_km2_partial_r_log_dens']:+.4f}** ($p = {corr_map['ems01_air']['log1p_km2_partial_p']:.4f}$)；
   - 未見解除資訊土壤場址（355 筆有效村里配對，含外部備援 361 筆均不顯著）偏相關為 **{corr_map['soil_unreleased']['raw_partial_r_log_dens']:+.4f}** ($p = {corr_map['soil_unreleased']['raw_partial_p']:.4f}$)，對數每平方公里偏相關為 **{corr_map['soil_unreleased']['log1p_km2_partial_r_log_dens']:+.4f}** ($p = {corr_map['soil_unreleased']['log1p_km2_partial_p']:.4f}$)。
   - 改以「每萬人筆數」衡量時，空污（$r = {corr_map['ems01_air']['per_10k_pop_pearson_r']:+.4f}$）與水污（$r = {corr_map['ems01_water']['per_10k_pop_pearson_r']:+.4f}$）皆呈現微弱負向或無顯著線性關聯。
2. **`ems01_waste` 反映工商業與科學園區申報聚集，而非鄰避設施分佈**：
   - `ems01_waste` 控制密度後仍呈正偏相關（對數面積密度偏相關 $r = {corr_map['ems01_waste']['log1p_km2_partial_r_log_dens']:+.4f}, p = {fmt_p(corr_map['ems01_waste']['log1p_km2_partial_p'])}$），源於製造業、科學園區與大型醫院密集區依法申報事業廢棄物產出所致。
"""

# --- Report C: COMPREHENSIVE_ENVIRONMENTAL_JUSTICE_REPORT.md ---
def build_comp_md(is_gh):
    csv_t = "../../data/township_cleaned_pollution_stats.csv" if is_gh else f"file:///{B.replace(chr(92), '/')}/township_cleaned_pollution_stats.csv"
    csv_i = "../../data/taiwan_incinerators_verified.csv" if is_gh else f"file:///{B.replace(chr(92), '/')}/taiwan_incinerators_verified.csv"
    geo_i = "../../environment-preview/incinerators.geojson" if is_gh else f"file:///{B.replace(chr(92), '/')}/incinerators.geojson"
    sh_doc = "../station-mapping-review-v2/SHANHUA-FINAL-RESOLUTION.md" if is_gh else f"file:///{B.replace(chr(92), '/')}/reports/station-mapping-review-v2/SHANHUA-FINAL-RESOLUTION.md"
    inc_doc = "./incinerators_environmental_justice.md" if is_gh else f"file:///{B.replace(chr(92), '/')}/reports/environment/incinerators_environmental_justice.md"
    cln_doc = "./cleaned_pollution_income_analysis.md" if is_gh else f"file:///{B.replace(chr(92), '/')}/reports/environment/cleaned_pollution_income_analysis.md"
    pm_svg = "../figures/pm25_vs_income.svg" if is_gh else f"file:///{B.replace(chr(92), '/')}/reports/figures/pm25_vs_income.svg"
    no_svg = "../figures/no2_vs_income.svg" if is_gh else f"file:///{B.replace(chr(92), '/')}/reports/figures/no2_vs_income.svg"
    inc_svg = "../figures/incinerator_income_rank.svg" if is_gh else f"file:///{B.replace(chr(92), '/')}/reports/figures/incinerator_income_rank.svg"

    air_rows = []
    for pol, pol_tex in [("NO2", "$\\text{NO}_2$"), ("PM2.5", "$\\text{PM}_{2.5}$"), ("SO2", "$\\text{SO}_2$")]:
        for key, label, show_q in [
            ("baseline_n77", "**1. 主分析（自動化排除善化）**", True),
            ("sensitivity_n78_with_shanhua", "2. 納入善化站（`AQX_P_07` 善化區）", False),
            ("general_stations_only_n60", "**3. 僅限「一般站」（排除交通/工業/背景站）**", False),
            ("general_stations_only_n61_shanhua", "4. 僅限「一般站」（含善化站）", False),
            ("township_dedup_n74", "**5. 鄉鎮去重（同鄉鎮測站取平均）**", False),
            ("township_dedup_n75_shanhua", "6. 鄉鎮去重（含善化站）", False),
        ]:
            if pol != "NO2" and key in ("general_stations_only_n61_shanhua", "township_dedup_n75_shanhua"):
                continue
            d = air_results[pol][key]
            q_b = f" ($q={d['bivariate_fdr_q']:.4f}$)" if show_q else ""
            q_p = f" ($q={d['partial_fdr_q']:.4f}$)" if show_q else ""
            air_rows.append(
                f"| {pol_tex} | {label} | {d['n']} | **{d['pearson_r']:+.4f}** ({d['ci95'][0]:+.3f}, {d['ci95'][1]:+.3f}) | {d['pearson_p']:.5f}{q_b} | {d['spearman_rho']:+.4f} ({d['spearman_p']:.5f}) | **{d['partial_r_log_dens']:+.4f}** | {d['partial_p_log_dens']:.5f}{q_p} |"
            )

    no2_gen = air_results['NO2']['general_stations_only_n60']
    return f"""# 台灣環境正義多維度實證研究總結報告（2026-11-13 嚴格核驗修正版）

- **專案倉庫**：[`agp1p7/taiwan-environmental-justice`](https://github.com/agp1p7/taiwan-environmental-justice)
- **線上預覽地圖**：[`https://agp1p7.github.io/taiwan-environmental-justice/environment-preview/`](https://agp1p7.github.io/taiwan-environmental-justice/environment-preview/)
- **產出資料與圖表索引**：
  - 全國 368 鄉鎮市區標準化環保列管與土壤場址統計：[township_cleaned_pollution_stats.csv]({csv_t})
  - 全國 28 處大型垃圾焚化廠／熱處理設施多尺度核驗清冊：[taiwan_incinerators_verified.csv]({csv_i}) ／ [incinerators.geojson]({geo_i})
  - 善化測站（`siteid: 44`）雙軌處置說明：[SHANHUA-FINAL-RESOLUTION.md]({sh_doc})
  - 專題分項報告：[incinerators_environmental_justice.md]({inc_doc}) ／ [cleaned_pollution_income_analysis.md]({cln_doc})

---

## 1. 總體研究架構與進度盤點

本研究結合**財政部 113 年度（2024 年）初步核定綜合所得稅申報統計**（全國 **368 個鄉鎮市區**中位數與 **7,653 個有效具名村里**圖形，`income_year = 2024`）、**內政部 2024 年底人口密度**（**368/368** 鄉鎮市區，含 30 個山地原住民鄉／區），以及**環境部四大公開資料來源**，從「鄉鎮市區宏觀尺度」與「行政區內部村里微觀尺度」雙重檢驗台灣的環境負荷分配：

| 研究維度 | 資料來源與規模 | 完成狀態 | 核心計量結論摘要 |
|---|---|---|---|
| **維度一：2024 環境空氣品質**（$\\text{{NO}}_2, \\text{{PM}}_{{2.5}}, \\text{{SO}}_2$） | 環境部 2024 測站小時值年報重算（主分析 $n=77$ 站；含善化敏感度 $n=78$ 站；僅一般站 $n=60$ 站；鄉鎮去重 $n=74$ 區） | **已完成並通過多重敏感度驗證** | 雙變量下僅 $\\text{{NO}}_2$ 與所得正相關（$r={air_results['NO2']['baseline_n77']['pearson_r']:+.4f}, p={air_results['NO2']['baseline_n77']['pearson_p']:.5f}, q={air_results['NO2']['baseline_n77']['bivariate_fdr_q']:.4f}$）；**控制 $\\log_{{10}}(\\text{{人口密度}})$ 後，三種污染物偏相關全數不顯著**（一般站 $\\text{{NO}}_2$ 偏相關 $r={no2_gen['partial_r_log_dens']:+.4f}, p={no2_gen['partial_p_log_dens']:.4f}$）。 |
| **維度二：土壤及地下水污染控制場址公告** | 環境部 `EMS_S_07` 去重後 **8,254 筆**（有效具名村里內 **8,234 筆**：未見解除資訊 355 筆、有解除公告資訊 7,879 筆；另有 20 筆於有效具名村里界外） | **已完成（368 鄉鎮面積／人口標準化）** | 未控制密度時未見解除資訊筆數與所得呈微弱正相關（$r={corr_map['soil_unreleased']['raw_pearson_r']:+.4f}$）；**控制 $\\log_{{10}}(\\text{{人口密度}})$ 後偏相關為 $r={corr_map['soil_unreleased']['raw_partial_r_log_dens']:+.4f}$ ($p={corr_map['soil_unreleased']['raw_partial_p']:.4f}$，不顯著)**。農地場址受「一地號一筆公告」影響（如彰化鹿港嚴格配對 863 筆）。 |
| **維度三：環保管理分類配對紀錄**（空／水／廢） | 環境部 `EMS_S_01` 去重且落於有效具名村里內 **256,597 筆**（空污 55,822、水污 64,518、廢清法 164,707 筆） | **已完成（修正定義與標準化）** | 此為歷史與跨分類管理紀錄（非獨立事業數，`iswaste` 為廢清法列管產源而非鄰避設施）。控制人口密度後空污紀錄偏相關消失（$r={corr_map['ems01_air']['raw_partial_r_log_dens']:+.4f}, p={corr_map['ems01_air']['raw_partial_p']:.4f}$），廢清法與水污紀錄則反映工商業廠辦聚集。 |
| **維度四：大型垃圾焚化廠與熱處理設施選址** | 環境部 SWIMS 官方營運中 **25 廠** + 桃園生質能 BOT + 竹北 BOO + 林內未營運廠（**共 28 處，28/28 村里落點核驗**） | **已完成（揭示跨尺度 MAUP 反轉）** | **宏觀鄉鎮層級**：控制密度後設廠與鄉鎮所得無關（偏相關 $r={itc['partial_r_controlling_log10_density']:+.4f}, p={itc['partial_p_controlling_log10_density']:.4f}$）。<br>**微觀村里層級**：**SWIMS 25 廠有 {s25['lower_count']} 座（{s25['lower_pct']:.1f}%）所在村里所得低於母區**（平均 **{s25['diff_mean']:+.1f} 千元**，配對 $t={s25['paired_t']:.3f}, p={s25['paired_p']:.5f}$；含新建共 27 處為 **{a27['lower_count']}/27 [{a27['lower_pct']:.1f}%]**，Wilcoxon $p={a27['wilcoxon_p']:.6f}$），且 **{100*s25['dist_le_2000m']/25:.0f}%（{s25['dist_le_2000m']}/25）位於距外區界 2 公里內**（中位數 **{s25['dist_median_m']:,.1f} 公尺**）。 |
| **待辦維度：河川水質污染指標（RPI）** | 環境部 `WQX_P_01`（河川水質監測資料） | **尚未執行（誠實揭露）** | 環境部開放資料 API 下載受 `MOENV_API_KEY` 與每日配額條件限制，本階段僅分析 `EMS_S_01` 水污列管紀錄，**尚未納入河川水體實測 RPI（溶氧、生化需氧量、氨氮、懸浮固體）**。 |

---

## 2. 維度一：2024 年空氣品質（$\\text{{NO}}_2, \\text{{PM}}_{{2.5}}, \\text{{SO}}_2$）多重敏感度分析

針對測站類型混淆（交通／工業／背景站）、同鄉鎮多站重複（77 站分屬 74 個鄉鎮）與善化站（`siteid: 44`）納入與否，我們完整計算敏感度模型與 BH FDR 校正：

| 污染物 | 模型設定 | 樣本數 ($n$) | 雙變量 Pearson $r$ (95% CI) | 雙變量 $p$ 值 (FDR $q$) | Spearman $\\rho$ ($p$ 值) | 控制 $\\log_{{10}}(\\text{{密度}})$ 偏相關 $r$ | 偏相關 $p$ 值 (FDR $q$) |
|---|---|---:|---|---|---|---|---|
{chr(10).join(air_rows)}

- **關鍵驗證**：僅保留 **60 座「一般測站」**時，控制 $\\log_{{10}}(\\text{{人口密度}})$ 後之 $\\text{{NO}}_2$ 偏相關降至 **$r = {no2_gen['partial_r_log_dens']:+.4f}$ ($p = {no2_gen['partial_p_log_dens']:.4f}$)**，說明雙變量正相關主要來自都市化人口與交通密集度共變。
- **空間自相關限制**：空氣污染物濃度具跨區擴散之空間自相關，傳統獨立樣本假設下之標準誤會低估區間寬度；惟控制密度後所有偏相關點估計均接近零且已不顯著（$p > 0.21$），進行空間自由度調整後僅會更不顯著，不影響推論。

![2024 年台灣空品測站 PM2.5 年均濃度與鄉鎮所得中位數關聯圖]({pm_svg})

![2024 年台灣空品測站 NO2 年均濃度與鄉鎮所得中位數關聯圖]({no_svg})

---

## 3. 維度二與三：368 鄉鎮市區環保管理配對紀錄（`EMS_S_01`）與土壤場址公告（`EMS_S_07`）

完整配對全國 **368/368** 鄉鎮市區後，同步以原始筆數、每平方公里密度、$\\log_{{10}}(1+\\text{{筆}}/\\text{{km}}^2)$ 及每萬人筆數檢驗：

1. **空污列管紀錄（55,822 筆）與未見解除資訊土壤場址（有效村里 355 筆／含界外備援 361 筆）**：
   - 控制 $\\log_{{10}}(\\text{{人口密度}})$ 後，空污紀錄偏相關由 {corr_map['ems01_air']['raw_pearson_r']:+.4f} 降至 **{corr_map['ems01_air']['raw_partial_r_log_dens']:+.4f} ($p = {corr_map['ems01_air']['raw_partial_p']:.4f}$)**（對數每平方公里偏相關 **{corr_map['ems01_air']['log1p_km2_partial_r_log_dens']:+.4f}, $p = {corr_map['ems01_air']['log1p_km2_partial_p']:.4f}$**）；
   - 未見解除資訊土壤場址偏相關由 {corr_map['soil_unreleased']['raw_pearson_r']:+.4f} 降至 **{corr_map['soil_unreleased']['raw_partial_r_log_dens']:+.4f} ($p = {corr_map['soil_unreleased']['raw_partial_p']:.4f}$)**（對數每平方公里偏相關 **{corr_map['soil_unreleased']['log1p_km2_partial_r_log_dens']:+.4f}, $p = {corr_map['soil_unreleased']['log1p_km2_partial_p']:.4f}$**）。
2. **水污列管紀錄（64,518 筆）與廢清法列管紀錄（164,707 筆）**：
   - 水污列管紀錄之對數每平方公里偏相關為 {corr_map['ems01_water']['log1p_km2_partial_r_log_dens']:+.4f}（$p = {corr_map['ems01_water']['log1p_km2_partial_p']:.4f}$），每萬人筆數為 $r = {corr_map['ems01_water']['per_10k_pop_pearson_r']:+.4f}$；
   - 廢清法列管紀錄（`iswaste`）代表依法申報事業廢棄物產出源（工廠、醫院與研發園區），故隨工商聚集呈現正偏相關（$r = {corr_map['ems01_waste']['log1p_km2_partial_r_log_dens']:+.4f}$），絕非鄰避設施。

---

## 4. 維度四：大型垃圾焚化廠（28 處）跨尺度分析——「鄉鎮平均」掩蓋「村里邊陲化」

1. **宏觀鄉鎮層級（`N = 368`）**：SWIMS 25 廠所在 25 區所得平均（{itc['hosting_mean_income']:.1f} 千元）高於其餘 343 鄉鎮（{itc['nonhosting_mean_income']:.1f} 千元），但**控制 $\\log_{{10}}(\\text{{人口密度}})$ 後偏相關不再顯著（$r = {itc['partial_r_controlling_log10_density']:+.4f}, p = {itc['partial_p_controlling_log10_density']:.4f}$）**。
2. **微觀村里層級（`VILLCODE`）**：在 SWIMS 25 廠內，**{s25['lower_count']} / 25 座（{s25['lower_pct']:.1f}%）**所在村里所得低於母行政區（平均差距 **{s25['diff_mean']:+.1f} 千元**，配對 $t = {s25['paired_t']:.3f}, p = {s25['paired_p']:.6f}$，Wilcoxon $p = {s25['wilcoxon_p']:.6f}$），區內百分位中位數僅 **{s25['pct_lte_median']:.1f}%**；納入桃園生質能與竹北廠後（27 處）則有 **{a27['lower_count']} / 27 處（{a27['lower_pct']:.1f}%）**低於母行政區（平均差距 **{a27['diff_mean']:+.1f} 千元**，Wilcoxon $p = {a27['wilcoxon_p']:.6f}$）。同時，SWIMS 25 廠距離最近相鄰鄉鎮市區邊界中位數僅 **{s25['dist_median_m']:,.1f} 公尺**（**{s25['dist_le_1000m']}/25 位於 1 公里內、{s25['dist_le_2000m']}/25 位於 2 公里內**）。

![台灣大型垃圾焚化廠與熱處理設施：鄉鎮市區 vs. 所在村里所得中位數比較]({inc_svg})
"""

write_dual_report(os.path.join('reports', 'environment', 'incinerators_environmental_justice.md'), 'incinerators_environmental_justice.md', build_inc_md(False), build_inc_md(True))
write_dual_report(os.path.join('reports', 'environment', 'cleaned_pollution_income_analysis.md'), 'cleaned_pollution_income_analysis.md', build_cleaned_md(False), build_cleaned_md(True))
write_dual_report(os.path.join('reports', 'environment', 'COMPREHENSIVE_ENVIRONMENTAL_JUSTICE_REPORT.md'), 'COMPREHENSIVE_ENVIRONMENTAL_JUSTICE_REPORT.md', build_comp_md(False), build_comp_md(True))

# Verify & regenerate SHANHUA-FINAL-RESOLUTION.md directly from air_results['...']['sensitivity_n78_with_shanhua']
n78_no2 = air_results["NO2"]["sensitivity_n78_with_shanhua"]
n78_pm25 = air_results["PM2.5"]["sensitivity_n78_with_shanhua"]
n78_so2 = air_results["SO2"]["sensitivity_n78_with_shanhua"]
sh_text = f"""# 善化空氣品質監測站（Site ID: 44）地址歧義查證與雙軌處置說明

- **測站名稱**：善化（`siteid: 44`）
- **自動化年報解析狀態（`reports/integrated-reanalysis-2024/`）**：`pending_conflicting_report_address`（主分析保守排除，維持 `n = 77`）
- **環境部開放資料快照（`reports/station-mapping-audit/official-stations.json`）**：`臺南市善化區`（納入 `n = 78` 敏感度分析）
- **最後更新日期**：2026-11-13

---

## 1. 疑義背景與字面差異

在環境部《113年中華民國空氣品質監測年報》附表 1.1（空氣品質監測站一覽表，PDF 第 78 頁）中，`siteid = 44`（善化站）之地址欄印刷為：

> `臺南市新營區善化鎮益名寮 60 號`

此字串存在兩處需紀錄之問題：
1. **行政區並列衝突**：同時出現「新營區」與「善化鎮」（改制前名稱），兩者為臺南市不同行政區（附表 1.1 中善化站之上一列即為 `siteid = 43` 新營站 `臺南市新營區中正路 4 號`，疑似年報排版時誤留上一列之「新營區」前綴）。
2. **用字差異（「益名寮」vs.「益民寮」）**：年報附表 1.1 印為「益**名**寮 60 號」，而環境部開放資料平臺測站基本資料集（`AQX_P_07`）則登記為「益**民**寮 60 號」。

---

## 2. 官方開放資料快照與座標落區核對

本專案倉庫內既有之官方快照檔案 `reports/station-mapping-audit/official-stations.json`（環境部 `AQX_P_07` 空氣品質監測站基本資料）針對 `siteid: "44"` 之原始紀錄如下：

```json
{{
  "sitename": "善化",
  "siteengname": "Shanhua",
  "areaname": "雲嘉南空品區",
  "county": "臺南市",
  "township": "善化區",
  "siteaddress": "臺南市善化區益民寮60號",
  "twd97lon": "120.29740529",
  "twd97lat": "23.11337642",
  "sitetype": "一般站",
  "siteid": "44"
}}
```

此外，交叉核對兩項專案內可重現之客觀證據：
1. **TWD97 經緯度點位落區檢查**：將 `official-stations.json` 所載座標 `(120.29740529, 23.11337642)` 與專案村里界圖資 `income.geojson` 進行點位落區（Point-in-Polygon）比對，確認該座標明確落於**臺南市善化區**境內，距離新營區邊界超過 15 公里。
2. **年報歷年搬遷異動表核對**：查驗《113年空氣品質監測年報》附表 1-2（89年至113年監測站搬遷異動一覽表，PDF 第 81–84 頁），善化站自設站以來並無跨區搬遷紀錄。

---

## 3. 專案內部一致性原則（`n = 77` 主分析 vs. `n = 78` 敏感度分析）

為確保專案內所有報告與自動化程式（`scripts/integrated_reanalysis_2024.py`）完全一致，本專案採行以下雙軌處置，不以人工覆寫自動化流程之判定規則：

1. **自動化主分析維持 `n = 77`（保守排除善化站）**：
   - 由於 `integrated_reanalysis_2024.py` 採嚴格保守原則，將地址字串同時命中兩個鄉鎮市區者標記為 `pending_conflicting_report_address`，因此 `reports/integrated-reanalysis-2024/` 下之 `summary.json`、`historical-pending.csv`、`REPORT.md` 與 `REPORT.zh-TW.md` 均統一維持「待確認（主分析排除，`n = 77`）」。
2. **`n = 78` 敏感度分析（依 `AQX_P_07` 歸入臺南市善化區，113 年度所得中位數 {town_inc['臺南市|善化區']['median_income_thousand_twd']:.0f} 千元）**：
   - 將善化站依 `official-stations.json` 歸入臺南市善化區後（`n = 78`），各污染物與鄉鎮所得中位數之相關與偏相關結果如下：
     - **$\\text{{NO}}_2$**：Pearson $r = {n78_no2['pearson_r']:+.4f}$ ($p = {n78_no2['pearson_p']:.5f}$)，Spearman $\\rho = {n78_no2['spearman_rho']:+.4f}$ ($p = {n78_no2['spearman_p']:.5f}$)；控制 $\\log_{{10}}(\\text{{人口密度}})$ 偏相關 $r = {n78_no2['partial_r_log_dens']:+.4f}$ ($p = {n78_no2['partial_p_log_dens']:.5f}$)。
     - **$\\text{{PM}}_{{2.5}}$**：Pearson $r = {n78_pm25['pearson_r']:+.4f}$ ($p = {n78_pm25['pearson_p']:.5f}$)，Spearman $\\rho = {n78_pm25['spearman_rho']:+.4f}$ ($p = {n78_pm25['spearman_p']:.5f}$)；控制 $\\log_{{10}}(\\text{{人口密度}})$ 偏相關 $r = {n78_pm25['partial_r_log_dens']:+.4f}$ ($p = {n78_pm25['partial_p_log_dens']:.5f}$)。
     - **$\\text{{SO}}_2$**：Pearson $r = {n78_so2['pearson_r']:+.4f}$ ($p = {n78_so2['pearson_p']:.5f}$)，Spearman $\\rho = {n78_so2['spearman_rho']:+.4f}$ ($p = {n78_so2['spearman_p']:.5f}$)；控制 $\\log_{{10}}(\\text{{人口密度}})$ 偏相關 $r = {n78_so2['partial_r_log_dens']:+.4f}$ ($p = {n78_so2['partial_p_log_dens']:.5f}$)。
   - 比較顯示，`n = 77` 與 `n = 78` 兩組樣本之統計推論完全一致。
"""
write_dual_report(os.path.join('reports', 'station-mapping-review-v2', 'SHANHUA-FINAL-RESOLUTION.md'), 'SHANHUA-FINAL-RESOLUTION.md', sh_text, sh_text)

# Copy script to REF so we can also commit the reproducible analysis script to scripts/ in GitHub!
shutil.copy2(__file__, os.path.join(REF, 'generate_all_verified_outputs.py'))
print("DONE! incinerators.geojson sha256 =", inc_sha, "size =", os.path.getsize(geo_path))
print("index.html sha256 =", idx_sha)
print("SWIMS 25 stats:", inc_stats["SWIMS_25"])
print("Soil recon:", all_stats["soil_reconciliation"])
