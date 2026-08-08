"""Run the real pipeline on diverse Indonesian points, then segment them."""
import sys
import time
import warnings

warnings.filterwarnings("ignore")
sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
sys.path.insert(0, ".")
import app

print("gee:", app.initialize_gee.__wrapped__())

SITES = [
    (-6.1938, 106.8230, "Jakarta Thamrin (CBD padat)"),
    (-6.2615, 106.8106, "Jakarta Selatan (urban)"),
    (-7.7956, 110.3695, "Yogyakarta (kota sedang)"),
    (-8.4095, 115.1889, "Bali Ubud (semi-rural)"),
    (-0.5035, 107.0018, "Laut Natuna (lepas pantai)"),
    (-2.9900, 104.7560, "Palembang (kota)"),
    (-8.2071, 120.6055, "NTT terpencil"),
]

rows = []
for lat, lon, label in SITES:
    t0 = time.time()
    result = app.run_analysis(lat, lon)
    feats = app.site_feature_vector(result)
    rows.append({"index": len(rows) + 1, "features": feats,
                 "decision": result.get("decision") or {}})
    have = sum(1 for v in feats.values() if v is not None)
    print(f"{label:32} {time.time()-t0:6.1f}s  fitur terisi {have}/10  skor={result.get('decision',{}).get('score')}")

print("\n=== SEGMENTASI ===")
seg = app.segment_sites(rows)
if not seg:
    print("tidak menghasilkan segmen")
    sys.exit(1)
print(f"k terpilih       : {seg['k']} (dipilih via silhouette)")
print(f"silhouette       : {seg['silhouette']:.3f}")
print(f"fitur dipakai    : {seg['features_used']}/10")
print(f"label per titik  : {seg['labels']}")
print(f"outlier          : {seg['outliers']}")
print()
for cluster, profile in sorted(seg["profiles"].items()):
    members = [SITES[i][2] for i, c in enumerate(seg["labels"]) if c == cluster]
    print(f"Segment {cluster+1} ({profile['size']} situs): {', '.join(profile['traits'])}")
    for m in members:
        print(f"     - {m}")
