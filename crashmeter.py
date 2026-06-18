#!/usr/bin/env python3
"""
Crashmeter (S&P 500) — hitung skor 0-4 dari data live, tulis data.json.
Pure stdlib, tidak perlu pip install apa pun.
Butuh environment variable FRED_API_KEY.
"""
import os, json, re, urllib.request, datetime

FRED_KEY = os.environ.get("FRED_API_KEY", "")
FRED = "https://api.stlouisfed.org/fred/series/observations"

# ---------- Konfigurasi (sesuaikan sendiri) ----------
LAST_INVERSION_END = datetime.date(2024, 12, 1)  # tanggal terakhir T10Y-3M inverted
TIER2_LAG_MONTHS   = 18                            # lag historis (midpoint 12-24 bln)
CAPE_FALLBACK      = 42.5                          # dipakai bila scrape Multpl gagal
SURGE_THRESHOLD_BPS = 150                          # B1: kenaikan HY OAS 6 bln
LEVEL_THRESHOLD_BPS = 550                          # B2: level HY OAS
CAPE_THRESHOLD      = 35                           # E
# -----------------------------------------------------


def fred(series_id, limit=400):
    url = (f"{FRED}?series_id={series_id}&api_key={FRED_KEY}"
           f"&file_type=json&sort_order=desc&limit={limit}")
    with urllib.request.urlopen(url, timeout=30) as r:
        raw = json.load(r)
    out = []
    for o in raw["observations"]:
        if o["value"] not in (".", ""):
            out.append((datetime.date.fromisoformat(o["date"]), float(o["value"])))
    return out  # terbaru dulu


def value_months_ago(series, months):
    target = datetime.date.today() - datetime.timedelta(days=int(months * 30.4))
    for d, v in series:
        if d <= target:
            return v
    return series[-1][1]


def scrape_cape():
    try:
        req = urllib.request.Request(
            "https://www.multpl.com/shiller-pe",
            headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=30) as r:
            html = r.read().decode("utf-8", "ignore")
        m = re.search(r"Current Shiller PE Ratio is\s*([\d.]+)", html)
        if m:
            return float(m.group(1))
    except Exception:
        pass
    return CAPE_FALLBACK


today = datetime.date.today()

# A — yield curve T10Y-3M
yc = fred("T10Y3M")
yc_date, yc_spread = yc[0]
yc_bps = yc_spread * 100
tier1 = yc_spread < 0
_m = LAST_INVERSION_END.month - 1 + TIER2_LAG_MONTHS
TIER2_WINDOW_END = datetime.date(LAST_INVERSION_END.year + _m // 12, _m % 12 + 1, 1)
tier2 = today <= TIER2_WINDOW_END

A = 1 if (tier1 or tier2) else 0

# B — HY OAS
hy = fred("BAMLH0A0HYM2")
hy_date, hy_now = hy[0]
hy_now_bps = hy_now * 100
hy_6mo_bps = value_months_ago(hy, 6) * 100
surge_bps = hy_now_bps - hy_6mo_bps
B1 = 1 if surge_bps >= SURGE_THRESHOLD_BPS else 0
B2 = 1 if hy_now_bps >= LEVEL_THRESHOLD_BPS else 0

# E — Shiller CAPE
cape = scrape_cape()
E = 1 if cape >= CAPE_THRESHOLD else 0

score = A + B1 + B2 + E
zone = "EXIT" if score >= 3 else ("Watch" if score == 2 else "Calm")

if tier1:
    a_note = f"Inverted, {yc_bps:.0f} bps (Tier 1)"
elif tier2:
    a_note = f"Tier 2 window s/d {TIER2_WINDOW_END:%b %Y}"
else:
    a_note = f"Normal, {yc_bps:.0f} bps"

data = {
    "updated": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
    "score": score,
    "max_score": 4,
    "zone": zone,
    "exit_signal": score >= 3,
    "exit_threshold": 3,
    "parameters": [
        {"id": "A",  "label": "Yield curve (T10Y-3M)",
         "value": A,  "reading": a_note},
        {"id": "B1", "label": f"HY OAS surge \u2265{SURGE_THRESHOLD_BPS} bps / 6 bln",
         "value": B1, "reading": f"\u0394 {surge_bps:+.0f} bps (6 bln)"},
        {"id": "B2", "label": f"HY OAS level \u2265{LEVEL_THRESHOLD_BPS} bps",
         "value": B2, "reading": f"{hy_now_bps:.0f} bps"},
        {"id": "E",  "label": f"Shiller CAPE \u2265{CAPE_THRESHOLD}",
         "value": E,  "reading": f"{cape:.1f}"},
    ],
    "sources": {
        "hy_oas_as_of": hy_date.isoformat(),
        "yield_curve_as_of": yc_date.isoformat(),
    },
}

with open("data.json", "w", encoding="utf-8") as f:
    json.dump(data, f, indent=2, ensure_ascii=False)
print(json.dumps(data, indent=2, ensure_ascii=False))
