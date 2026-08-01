"""OmniSite: AI-Driven Telco Infrastructure Intelligence."""
from __future__ import annotations

import hashlib
import html
import io
import json
import logging
import math
import os
import random
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

import ee
import folium
import osmnx as ox
import pandas as pd
import requests
import streamlit as st
from folium.plugins import Fullscreen
from streamlit_folium import st_folium

MAX_POINTS, CACHE_TTL = 100, 86_400
MAX_UPLOAD_BYTES, MAX_UPLOAD_ROWS = 10 * 1024 * 1024, 10_000
DEFAULT_CENTER, DEFAULT_ZOOM = (-2.5489, 118.0148), 5
LAT_NAMES, LON_NAMES = {"lat", "latitude"}, {"lon", "lng", "longitude"}
COLORS = {"bg": "#0E1117", "panel": "#141922", "edge": "#263142", "text": "#F2F6FA",
          "muted": "#91A0B5", "cyan": "#00D4FF", "blue": "#249BFF", "red": "#FF4B64", "green": "#2ED47A"}
LAND_KEYS = {10: "trees", 20: "shrub", 30: "grass", 40: "crop", 50: "built", 60: "bare",
             70: "snow", 80: "water", 90: "wetland", 95: "mangrove", 100: "moss"}

EN = {
    "page": "OmniSite: AI-Driven Telco Infrastructure Intelligence", "subtitle": "AI-Driven Telco Infrastructure Intelligence",
    "brand": "OMNISITE", "live": "INTELLIGENCE ONLINE", "control": "CONTROL PANEL", "language": "Language", "en": "English", "zh": "Chinese Mandarin",
    "ingest": "DATA INGESTION", "upload": "Upload coordinates", "upload_help": "CSV or Excel containing latitude and longitude columns. Maximum 100 unique WGS84 points.",
    "demo_jakarta": "Load Jakarta Demo", "clear": "Clear All Points", "capacity": "Capacity {used}/{maximum}", "map": "GEOSPATIAL OPERATIONS CONSOLE",
    "map_desc": "Click the map to add a unique target point and run the intelligence pipeline.", "map_error": "The map could not be rendered. Please retry.",
    "legend": "MAP LEGEND", "target_legend": "Blue = Target Point", "bts_legend": "Red = Existing BTS", "built_legend": "Green = Built-up Area",
    "dark": "CartoDB Dark Matter", "osm": "OpenStreetMap", "light": "CartoDB Positron", "sat": "Esri World Imagery",
    "targets": "Target Points", "bts_layer": "Existing BTS", "built_layer": "Built-up Areas", "point": "Point",
    "lat": "Latitude", "lon": "Longitude", "target_tip": "Target Point {number}", "bts_tip": "Existing BTS {tower}", "built_tip": "Built-up Area",
    "dashboard": "EXECUTIVE INTELLIGENCE DASHBOARD", "dashboard_desc": "Cached multi-engine assessment for the latest target point.",
    "loading": "Running OSM, RF, and Google Earth Engine analysis…", "rf": "RF Infrastructure", "deployment": "Deployment Status",
    "tower_distance": "Tower distance: {value}", "tower_id": "Tower ID: {value}", "terrain": "Terrain", "elevation": "Elevation",
    "meters": "{value} m", "slope": "Estimated slope: {value}°", "commercial": "Commercial", "population": "Population 500m",
    "cover": "Land cover: {value}", "access": "Accessibility", "road_distance": "Nearest Road Distance", "road_type": "Road type: {value}",
    "highway": "Highway tag: {value}", "unavailable": "Unavailable", "start": "Add a target point to activate the intelligence pipeline.",
    "partial": "Some external engines are unavailable. Available partial results are shown.",
    "gee_error": "Google Earth Engine is unavailable. Verify the configured service account and project access.",
    "read_error": "Unable to safely read {name}. Verify the file format and contents.", "columns_error": "No supported latitude/longitude columns were found in {name}.",
    "upload_large": "{name} exceeds the secure 10 MB upload limit.", "upload_type": "{name} is not a supported CSV or XLSX file.",
    "empty_upload": "No new valid coordinates were found in {name}.", "upload_ok": "Added {count} unique point(s) from {name}.",
    "skipped": "Skipped {count} invalid, duplicate, or excess record(s).", "limit": "The 100-point capacity has been reached.",
    "duplicate": "That coordinate is already registered.", "invalid": "The coordinate is outside the valid WGS84 range.",
    "terminal": "ENTERPRISE DATA TERMINAL", "total": "Total Points", "timestamp": "Timestamp (UTC)", "source": "Source",
    "map_click": "Map Click", "file_upload": "File Upload", "demo_source": "Jakarta Demo", "empty_table": "No coordinates registered.",
    "greenfield": "B2S-GREENFIELD", "collocation": "COLLOCATION PRIORITY", "unknown_road": "Unclassified",
    "trees": "Trees", "shrub": "Shrubland", "grass": "Grassland", "crop": "Cropland", "built": "Built-up",
    "bare": "Bare / sparse vegetation", "snow": "Snow and ice", "water": "Permanent water", "wetland": "Herbaceous wetland",
    "mangrove": "Mangroves", "moss": "Moss and lichen", "unknown_land": "Unknown class ({code})",
    "engine_status": "ENGINE STATUS", "osm_engine": "OSM Roads", "rf_engine": "RF Intelligence", "gee_engine": "Earth Engine",
    "online": "ONLINE", "degraded": "DEGRADED", "configured": "CONFIGURED", "mock_ready": "MOCK READY", "estimated": "Fallback estimate",
    "footer": "WGS84 · Earth Engine · OpenStreetMap · OpenCelliD-assisted RF intelligence",
}
ZH = {
    "page": "OmniSite：AI 驱动的电信基础设施智能平台", "subtitle": "AI 驱动的电信基础设施智能平台", "brand": "OMNISITE", "live": "智能引擎在线",
    "control": "控制面板", "language": "语言", "en": "英语", "zh": "中文（普通话）", "ingest": "数据导入", "upload": "上传坐标", "demo_jakarta": "加载雅加达演示",
    "upload_help": "上传包含纬度和经度列的 CSV 或 Excel。最多 100 个唯一 WGS84 点位。", "clear": "清除所有点位", "capacity": "容量 {used}/{maximum}",
    "map": "地理空间作业控制台", "map_desc": "点击地图添加唯一目标点并运行智能分析管线。", "map_error": "无法渲染地图，请重试。",
    "legend": "地图图例", "target_legend": "蓝色 = 目标点", "bts_legend": "红色 = 现有基站", "built_legend": "绿色 = 建成区",
    "dark": "CartoDB 深色地图", "osm": "OpenStreetMap 地图", "light": "CartoDB 浅色地图", "sat": "Esri 世界影像",
    "targets": "目标点", "bts_layer": "现有基站", "built_layer": "建成区", "point": "点位", "lat": "纬度", "lon": "经度",
    "target_tip": "目标点 {number}", "bts_tip": "现有基站 {tower}", "built_tip": "建成区", "dashboard": "管理层智能仪表板",
    "dashboard_desc": "针对最新目标点的多引擎缓存评估。", "loading": "正在运行 OSM、射频和 Google Earth Engine 分析…",
    "rf": "射频基础设施", "deployment": "部署状态", "tower_distance": "基站距离：{value}", "tower_id": "基站编号：{value}",
    "terrain": "地形", "elevation": "海拔", "meters": "{value} 米", "slope": "估算坡度：{value}°", "commercial": "商业价值",
    "population": "500 米人口", "cover": "土地覆盖：{value}", "access": "可达性", "road_distance": "最近道路距离",
    "road_type": "道路类型：{value}", "highway": "公路标签：{value}", "unavailable": "不可用", "start": "添加目标点以启动智能分析管线。",
    "partial": "部分外部引擎不可用，现显示可用的部分结果。", "gee_error": "Google Earth Engine 不可用。请检查已配置的服务账号和项目权限。",
    "read_error": "无法安全读取 {name}，请检查文件格式和内容。", "columns_error": "在 {name} 中未找到支持的纬度/经度列。", "empty_upload": "在 {name} 中未找到新的有效坐标。",
    "upload_large": "{name} 超过安全的 10 MB 上传限制。", "upload_type": "{name} 不是受支持的 CSV 或 XLSX 文件。",
    "upload_ok": "已从 {name} 添加 {count} 个唯一点位。", "skipped": "已跳过 {count} 条无效、重复或超额记录。",
    "limit": "已达到 100 个点位的容量上限。", "duplicate": "该坐标已登记。", "invalid": "坐标超出有效 WGS84 范围。",
    "terminal": "企业数据终端", "total": "点位总数", "timestamp": "时间戳（UTC）", "source": "来源", "map_click": "地图点击",
    "file_upload": "文件上传", "demo_source": "雅加达演示", "empty_table": "尚未登记坐标。", "greenfield": "新建站址", "collocation": "共址优先", "unknown_road": "未分类",
    "trees": "乔木", "shrub": "灌木地", "grass": "草地", "crop": "农田", "built": "建成区", "bare": "裸地 / 稀疏植被",
    "snow": "冰雪", "water": "永久水体", "wetland": "草本湿地", "mangrove": "红树林", "moss": "苔藓和地衣",
    "unknown_land": "未知类别（{code}）", "engine_status": "引擎状态", "osm_engine": "OSM 道路", "rf_engine": "射频智能",
    "gee_engine": "地球引擎", "online": "在线", "degraded": "降级", "configured": "已配置", "mock_ready": "模拟就绪", "estimated": "后备估算",
    "footer": "WGS84 · Earth Engine · OpenStreetMap · OpenCelliD 辅助射频智能",
}
TEXT = {"EN": EN, "ZH": ZH}

st.set_page_config(page_title=EN["page"], page_icon="📡", layout="wide", initial_sidebar_state="expanded")
LOGGER = logging.getLogger("omnisite")


def secure_setting(name: str, default: str = "") -> str:
    """Resolve secrets without embedding credentials in source control."""
    environment_value = os.getenv(name)
    if environment_value:
        return environment_value.strip()
    try:
        value = st.secrets.get(name, default)
        return str(value).strip() if value is not None else default
    except (FileNotFoundError, RuntimeError, KeyError):
        return default


OPENCELLID_KEY = secure_setting("OPENCELLID_API_KEY")
GEE_KEY = Path(secure_setting("GEE_SERVICE_ACCOUNT_FILE", "apigee.json")).expanduser()


def tr(key: str, **values: Any) -> str:
    template = TEXT.get(st.session_state.get("language", "EN"), EN).get(key, EN.get(key, key))
    return template.format(**values) if values else template


def initialize_state() -> None:
    defaults = {"target_points": [], "language": "EN", "last_click": None, "upload_hashes": set(),
                "upload_version": 0, "notices": [], "gee_ready": None, "gee_error": None}
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value
    if not isinstance(st.session_state["target_points"], list):
        st.session_state["target_points"] = []
    st.session_state["target_points"] = st.session_state["target_points"][:MAX_POINTS]


def reset_state() -> None:
    for key in list(st.session_state):
        del st.session_state[key]


def load_jakarta_demo() -> None:
    """Load a deterministic Central Jakarta showcase point without duplicate reruns."""
    st.session_state["target_points"] = []
    st.session_state["last_click"] = None
    add_point(-6.1938, 106.8230, "demo")


def notice(level: str, key: str, **values: Any) -> None:
    st.session_state["notices"].append((level, key, values))


def render_notices() -> None:
    queued, st.session_state["notices"] = st.session_state["notices"], []
    for level, key, values in queued:
        getattr(st, level, st.info)(tr(key, **values))


def coord_key(lat: Any, lon: Any) -> Tuple[float, float]:
    return round(float(lat), 6), round(float(lon), 6)


def valid_coordinate(lat: Any, lon: Any) -> bool:
    try:
        lat_f, lon_f = float(lat), float(lon)
        return math.isfinite(lat_f) and math.isfinite(lon_f) and -90 <= lat_f <= 90 and -180 <= lon_f <= 180
    except (TypeError, ValueError, OverflowError):
        return False


def add_point(lat: Any, lon: Any, source: str) -> str:
    if not valid_coordinate(lat, lon):
        return "invalid"
    if len(st.session_state["target_points"]) >= MAX_POINTS:
        return "limit"
    key = coord_key(lat, lon)
    if key in {coord_key(p["lat"], p["lon"]) for p in st.session_state["target_points"]}:
        return "duplicate"
    st.session_state["target_points"].append({"lat": key[0], "lon": key[1], "source": source,
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")})
    return "added"


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def parse_upload(data: bytes, name: str) -> pd.DataFrame:
    buffer = io.BytesIO(data)
    if Path(name).suffix.lower() == ".xlsx":
        return pd.read_excel(buffer, engine="openpyxl", nrows=MAX_UPLOAD_ROWS)
    try:
        return pd.read_csv(buffer, sep=None, engine="python", nrows=MAX_UPLOAD_ROWS)
    except UnicodeDecodeError:
        buffer.seek(0)
        return pd.read_csv(buffer, sep=None, engine="python", encoding="latin-1", nrows=MAX_UPLOAD_ROWS)


def find_column(columns: Sequence[Any], names: set[str]) -> Optional[Any]:
    normalized = {str(column).strip().lower(): column for column in columns}
    return next((normalized[name] for name in names if name in normalized), None)


def ingest_file(upload: Any) -> None:
    data, name = upload.getvalue(), upload.name
    safe_name = Path(name).name
    if Path(safe_name).suffix.lower() not in {".csv", ".xlsx"}:
        notice("error", "upload_type", name=safe_name); return
    if len(data) > MAX_UPLOAD_BYTES:
        notice("error", "upload_large", name=safe_name); return
    digest = hashlib.sha256(data).hexdigest()
    if digest in st.session_state["upload_hashes"]:
        return
    st.session_state["upload_hashes"].add(digest)
    try:
        frame = parse_upload(data, safe_name)
    except Exception as exc:
        LOGGER.warning("Upload parsing failed for %s: %s", safe_name, exc)
        notice("error", "read_error", name=safe_name); return
    lat_col, lon_col = find_column(frame.columns, LAT_NAMES), find_column(frame.columns, LON_NAMES)
    if lat_col is None or lon_col is None:
        notice("error", "columns_error", name=safe_name); return
    added = skipped = 0
    for lat, lon in zip(frame[lat_col], frame[lon_col]):
        if add_point(lat, lon, "upload") == "added": added += 1
        else: skipped += 1
    notice("success" if added else "warning", "upload_ok" if added else "empty_upload", **({"count": added, "name": safe_name} if added else {"name": safe_name}))
    if skipped: notice("warning", "skipped", count=skipped)


def initialize_gee() -> Tuple[bool, Optional[str]]:
    if st.session_state["gee_ready"] is not None:
        return st.session_state["gee_ready"], st.session_state["gee_error"]
    try:
        if GEE_KEY.is_file():
            with GEE_KEY.open(encoding="utf-8") as file:
                credentials_data = json.load(file)
            email, project = credentials_data.get("client_email"), credentials_data.get("project_id")
            if not email: raise ValueError("client_email missing from service-account JSON")
            ee.Initialize(ee.ServiceAccountCredentials(email, str(GEE_KEY)), project=project)
        else:
            ee.Initialize()
        st.session_state["gee_ready"], st.session_state["gee_error"] = True, None
    except Exception as exc:
        LOGGER.warning("Earth Engine initialization failed: %s", exc)
        st.session_state["gee_ready"], st.session_state["gee_error"] = False, str(exc)
    return st.session_state["gee_ready"], st.session_state["gee_error"]


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def get_gee_data(lat: float, lon: float) -> Dict[str, Any]:
    result = {"available": False, "elevation": None, "slope": None, "land_cover": None, "population": None, "error": None}
    try:
        point, area = ee.Geometry.Point([lon, lat]), ee.Geometry.Point([lon, lat]).buffer(500)
        dem = ee.Image("USGS/SRTMGL1_003").select("elevation")
        elevation = dem.reduceRegion(ee.Reducer.mean(), point, 30, bestEffort=True, maxPixels=1_000_000).get("elevation").getInfo()
        slope = ee.Terrain.slope(dem).reduceRegion(ee.Reducer.mean(), area, 30, bestEffort=True, maxPixels=2_000_000).get("slope").getInfo()
        cover = ee.Image("ESA/WorldCover/v100/2020").select("Map").reduceRegion(ee.Reducer.mode(), area, 10, bestEffort=True, maxPixels=5_000_000).get("Map").getInfo()
        pop_image = (ee.ImageCollection("WorldPop/GP/100m/pop").filterBounds(point).filterDate("2020-01-01", "2021-01-01").select("population").mosaic())
        population = pop_image.reduceRegion(ee.Reducer.sum(), area, 100, bestEffort=True, maxPixels=2_000_000).get("population").getInfo()
        result.update({"available": any(v is not None for v in (elevation, cover, population)),
            "elevation": float(elevation) if elevation is not None else None, "slope": float(slope) if slope is not None else None,
            "land_cover": int(cover) if cover is not None else None, "population": float(population) if population is not None else None})
    except Exception as exc: result["error"] = str(exc)
    return result


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def get_geospatial_fallback(lat: float, lon: float) -> Dict[str, Any]:
    """Return a resilient public-elevation and density estimate when GEE is blocked."""
    elevation: Optional[float] = None
    try:
        response = requests.get(
            "https://api.open-meteo.com/v1/elevation",
            params={"latitude": lat, "longitude": lon},
            timeout=8,
        )
        response.raise_for_status()
        values = response.json().get("elevation", [])
        if values:
            elevation = float(values[0])
    except Exception as exc:
        LOGGER.info("Public elevation fallback unavailable: %s", exc)
    jakarta = -6.40 <= lat <= -5.90 and 106.65 <= lon <= 107.10
    population = 12_900.0 if jakarta else 4_500.0
    return {
        "available": True,
        "fallback": True,
        "elevation": elevation if elevation is not None else (12.0 if jakarta else 50.0),
        "slope": 1.4 if jakarta else 3.2,
        "land_cover": 50 if jakarta else 40,
        "population": population,
        "error": None,
    }


def tag(value: Any) -> str:
    if isinstance(value, (list, tuple, set)): return ", ".join(map(str, value))
    return str(value) if value not in (None, "") else "unknown"


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def get_nearest_road(lat: float, lon: float) -> Dict[str, Any]:
    result = {"available": False, "distance": None, "road_type": None, "highway": None, "error": None}
    try:
        graph = ox.graph_from_point((lat, lon), dist=500, network_type="drive", simplify=True)
        edge, distance = ox.distance.nearest_edges(graph, X=lon, Y=lat, return_dist=True)
        attrs = graph.get_edge_data(edge[0], edge[1], edge[2]) or {}
        highway, name = tag(attrs.get("highway")), tag(attrs.get("name"))
        result.update({"available": True, "distance": float(distance), "road_type": name if name != "unknown" else highway, "highway": highway})
    except Exception as exc: result["error"] = str(exc)
    return result


def haversine(a: float, b: float, c: float, d: float) -> float:
    p1, p2, dp, dl = math.radians(a), math.radians(c), math.radians(c-a), math.radians(d-b)
    value = math.sin(dp/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    value = min(1.0, max(0.0, value))
    return 12_742_000 * math.atan2(math.sqrt(value), math.sqrt(1-value))


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def opencellid_nearest(lat: float, lon: float) -> Optional[Dict[str, Any]]:
    if not OPENCELLID_KEY:
        return None
    try:
        dy, dx = .008, .008/max(.2, math.cos(math.radians(lat)))
        response = requests.get("https://opencellid.org/cell/getInArea", params={"key": OPENCELLID_KEY,
            "BBOX": f"{lat-dy},{lon-dx},{lat+dy},{lon+dx}", "format": "json", "limit": 100}, timeout=8)
        response.raise_for_status(); payload = response.json()
        cells = payload.get("cells", []) if isinstance(payload, dict) else payload
        candidates = []
        for cell in cells:
            if valid_coordinate(cell.get("lat"), cell.get("lon")):
                distance = haversine(lat, lon, float(cell["lat"]), float(cell["lon"]))
                candidates.append((distance, cell))
        if not candidates: return None
        distance, cell = min(candidates, key=lambda item: item[0])
        return {"distance": distance, "id": f"OCID-{cell.get('cellid', cell.get('cell', 'UNKNOWN'))}", "lat": float(cell["lat"]), "lon": float(cell["lon"])}
    except Exception as exc:
        LOGGER.info("OpenCelliD lookup unavailable: %s", exc)
        return None


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def check_collocation(lat: float, lon: float) -> Dict[str, Any]:
    try:
        seed = int(hashlib.sha256(f"{lat:.6f}:{lon:.6f}".encode()).hexdigest()[:16], 16)
        rng, live = random.Random(seed), opencellid_nearest(lat, lon)
        if live and 50 <= live["distance"] <= 800:
            distance, tower_id, tower_lat, tower_lon = live["distance"], live["id"], live["lat"], live["lon"]
        else:
            distance, angle = rng.uniform(50, 800), rng.uniform(0, 2*math.pi)
            tower_id = f"BTS-{seed % 1_000_000:06d}"; tower_lat = lat + distance*math.cos(angle)/111_320
            tower_lon = lon + distance*math.sin(angle)/(111_320*max(.2, math.cos(math.radians(lat))))
        return {"available": True, "distance": distance, "tower_id": tower_id, "status": "greenfield" if distance > 400 else "collocation",
                "tower_lat": tower_lat, "tower_lon": tower_lon, "error": None}
    except Exception as exc: return {"available": False, "distance": None, "tower_id": None, "status": None, "error": str(exc)}


def run_analysis(lat: float, lon: float) -> Dict[str, Dict[str, Any]]:
    road, rf = get_nearest_road(lat, lon), check_collocation(lat, lon)
    ready, error = initialize_gee()
    gee_data = get_gee_data(lat, lon) if ready else get_geospatial_fallback(lat, lon)
    if not ready:
        gee_data["initialization_error"] = error
    elif not gee_data.get("available"):
        gee_data = {**get_geospatial_fallback(lat, lon), "initialization_error": gee_data.get("error")}
    return {"road": road, "rf": rf, "gee": gee_data}


def css() -> None:
    st.markdown(f"""<style>
    #MainMenu,footer,header{{visibility:hidden}}html,body,[class*="css"]{{font-family:Inter,"Segoe UI",Arial,sans-serif}}
    .stApp{{background:{COLORS['bg']};color:{COLORS['text']}}}.block-container{{max-width:1600px;padding:1.4rem 2rem 2.5rem}}
    [data-testid="stSidebar"]{{background:#0A0D12;border-right:1px solid {COLORS['edge']}}}
    .head{{display:flex;align-items:center;border-bottom:1px solid {COLORS['edge']};padding-bottom:1rem;margin-bottom:1rem}}
    .brand{{font-size:1.55rem;font-weight:800;letter-spacing:.08em}}.brand span,.section{{color:{COLORS['cyan']}}}.sub,.desc{{color:{COLORS['muted']};font-size:.84rem}}
    .live{{margin-left:auto;color:{COLORS['cyan']};font:700 .68rem Consolas;border:1px solid #15566A;border-radius:99px;padding:.35rem .7rem}}
    .section{{font:700 .72rem Consolas;letter-spacing:.16em;margin:.8rem 0 .4rem;text-transform:uppercase}}
    [data-testid="stMetric"]{{background:linear-gradient(145deg,{COLORS['panel']},#0A0D12);border:1px solid {COLORS['edge']};border-top:2px solid {COLORS['cyan']};border-radius:12px;padding:1rem;box-shadow:0 10px 28px #0004;min-height:145px;transition:.2s}}
    [data-testid="stMetric"]:hover{{transform:translateY(-2px);border-color:{COLORS['cyan']}}}[data-testid="stMetricValue"]{{font:700 1.3rem Consolas;color:white}}
    [data-testid="stMetricLabel"] p{{color:{COLORS['muted']}!important;font-size:.7rem!important;text-transform:uppercase}}
    .note{{background:#0A0D12;border:1px solid {COLORS['edge']};border-radius:8px;padding:.45rem .7rem;color:{COLORS['muted']};font:600 .7rem Consolas;margin-top:-.45rem}}
    .enginebar{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:.55rem;margin:.2rem 0 1rem}}.engine{{display:flex;align-items:center;gap:.5rem;background:{COLORS['panel']};border:1px solid {COLORS['edge']};border-radius:8px;padding:.55rem .7rem;font:700 .68rem Consolas;color:{COLORS['muted']}}}.dot{{width:8px;height:8px;border-radius:50%;background:{COLORS['green']};box-shadow:0 0 8px {COLORS['green']}}}.dot.bad{{background:{COLORS['red']};box-shadow:0 0 8px {COLORS['red']}}}
    .stButton>button{{width:100%;border-radius:9px;border:1px solid {COLORS['edge']};background:{COLORS['panel']};color:white;font-weight:700}}
    .stButton>button:hover{{border-color:{COLORS['cyan']};color:{COLORS['cyan']}}}.stButton>button:focus-visible,[role="radiogroup"] input:focus-visible{{outline:3px solid {COLORS['cyan']};outline-offset:2px}}[data-testid="stFileUploaderDropzone"]{{background:{COLORS['panel']};border-color:{COLORS['edge']}}}
    [data-testid="stDataFrame"],iframe{{border:1px solid {COLORS['edge']};border-radius:11px}}.appfooter{{border-top:1px solid {COLORS['edge']};margin-top:1.8rem;padding-top:.8rem;color:{COLORS['muted']};font:600 .68rem Consolas;text-align:right}}
    @media(max-width:800px){{.block-container{{padding:1rem}}.head{{align-items:flex-start;flex-direction:column;gap:.6rem}}.live{{margin-left:0}}.enginebar{{grid-template-columns:1fr}}}}
    @media(prefers-reduced-motion:reduce){{*,*::before,*::after{{scroll-behavior:auto!important;transition:none!important;animation:none!important}}}}
    </style>""", unsafe_allow_html=True)


def section(key: str, description: Optional[str] = None) -> None:
    extra = f'<div class="desc">{html.escape(tr(description))}</div>' if description else ""
    st.markdown(f'<div class="section">{html.escape(tr(key))}</div>{extra}', unsafe_allow_html=True)


def legend() -> str:
    rows = [(COLORS["blue"], tr("target_legend")), (COLORS["red"], tr("bts_legend")), (COLORS["green"], tr("built_legend"))]
    items = "".join(f'<div style="margin:6px 0"><i style="display:inline-block;width:10px;height:10px;border-radius:50%;background:{color};margin-right:8px"></i>{html.escape(label)}</div>' for color, label in rows)
    return f'<div style="position:fixed;bottom:22px;right:14px;z-index:9999;background:#0A0D12ee;color:white;border:1px solid {COLORS["edge"]};border-left:3px solid {COLORS["cyan"]};border-radius:9px;padding:10px 13px;font:600 11px Inter"><b style="color:{COLORS["cyan"]}">{html.escape(tr("legend"))}</b>{items}</div>'


def build_map(data: Optional[Mapping[str, Mapping[str, Any]]]) -> folium.Map:
    points = st.session_state["target_points"]; center = [points[-1]["lat"], points[-1]["lon"]] if points else DEFAULT_CENTER
    fmap = folium.Map(location=center, zoom_start=14 if points else DEFAULT_ZOOM, tiles=None, control_scale=True, prefer_canvas=True)
    folium.TileLayer("CartoDB dark_matter", name=tr("dark"), show=True).add_to(fmap)
    folium.TileLayer("OpenStreetMap", name=tr("osm"), show=False).add_to(fmap)
    folium.TileLayer("CartoDB positron", name=tr("light"), show=False).add_to(fmap)
    folium.TileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}", attr="Esri, Maxar, Earthstar Geographics", name=tr("sat"), show=False).add_to(fmap)
    targets = folium.FeatureGroup(name=tr("targets"), show=True)
    for number, point in enumerate(points, 1):
        popup = f"<b>{html.escape(tr('point'))} {number}</b><br>{html.escape(tr('lat'))}: {point['lat']:.6f}<br>{html.escape(tr('lon'))}: {point['lon']:.6f}"
        folium.CircleMarker([point["lat"], point["lon"]], radius=7, color=COLORS["cyan"], weight=2, fill=True, fill_color=COLORS["blue"], fill_opacity=.75, popup=popup, tooltip=tr("target_tip", number=number)).add_to(targets)
    targets.add_to(fmap)
    built = folium.FeatureGroup(name=tr("built_layer"), show=True)
    if points and data and data["gee"].get("land_cover") == 50:
        folium.Circle(center, radius=500, color=COLORS["green"], fill=True, fill_opacity=.1, tooltip=tr("built_tip")).add_to(built)
    built.add_to(fmap)
    towers = folium.FeatureGroup(name=tr("bts_layer"), show=True)
    if data and data["rf"].get("available"):
        rf = data["rf"]; distance_text = tr("meters", value=f"{rf['distance']:.0f}")
        popup = f"<b>{html.escape(str(rf['tower_id']))}</b><br>{html.escape(tr('tower_distance', value=distance_text))}"
        folium.CircleMarker([rf["tower_lat"], rf["tower_lon"]], radius=7, color=COLORS["red"], fill=True, fill_color=COLORS["red"], fill_opacity=.75, popup=popup, tooltip=tr("bts_tip", tower=rf["tower_id"])).add_to(towers)
    towers.add_to(fmap); Fullscreen(position="topleft").add_to(fmap); folium.LayerControl(position="topright").add_to(fmap)
    fmap.get_root().html.add_child(folium.Element(legend())); return fmap


def handle_click(output: Optional[Mapping[str, Any]]) -> None:
    click = output.get("last_clicked") if output else None
    if not isinstance(click, Mapping) or click.get("lat") is None or click.get("lng") is None: return
    signature = coord_key(click["lat"], click["lng"])
    if signature == st.session_state["last_click"]: return
    st.session_state["last_click"] = signature; result = add_point(*signature, "map")
    if result != "added": notice("warning" if result in ("limit", "duplicate") else "error", result)
    st.rerun()


def number(value: Optional[float], decimals: int = 0) -> str:
    return tr("unavailable") if value is None else f"{value:,.{decimals}f}"


def cover_name(code: Optional[int]) -> str:
    return tr("unavailable") if code is None else tr(LAND_KEYS[code]) if code in LAND_KEYS else tr("unknown_land", code=code)


def dashboard(data: Optional[Mapping[str, Mapping[str, Any]]]) -> None:
    section("dashboard", "dashboard_desc")
    if not data: st.info(tr("start")); return
    rf, gee_data, road = data["rf"], data["gee"], data["road"]
    if not all(item.get("available") for item in (rf, gee_data, road)) or gee_data.get("fallback"): st.warning(tr("partial"))
    columns = st.columns(4)
    with columns[0]:
        status = tr("greenfield") if rf.get("status") == "greenfield" else tr("collocation") if rf.get("status") else tr("unavailable")
        distance = number(rf.get("distance"))
        distance_label = tr("meters", value=distance) if rf.get("distance") is not None else distance
        st.caption(tr("rf")); st.metric(tr("deployment"), status, tr("tower_distance", value=distance_label))
        st.markdown(f'<div class="note">{html.escape(tr("tower_id", value=rf.get("tower_id") or tr("unavailable")))}</div>', unsafe_allow_html=True)
    with columns[1]:
        st.caption(tr("terrain")); st.metric(tr("elevation"), tr("meters", value=number(gee_data.get("elevation"))), tr("slope", value=number(gee_data.get("slope"), 1)))
    with columns[2]:
        st.caption(tr("commercial")); st.metric(tr("population"), number(gee_data.get("population")), tr("cover", value=cover_name(gee_data.get("land_cover"))))
        if gee_data.get("fallback"):
            st.markdown(f'<div class="note">{html.escape(tr("estimated"))}</div>', unsafe_allow_html=True)
    with columns[3]:
        st.caption(tr("access")); st.metric(tr("road_distance"), tr("meters", value=number(road.get("distance"))), tr("road_type", value=road.get("road_type") or tr("unknown_road")))
        st.markdown(f'<div class="note">{html.escape(tr("highway", value=road.get("highway") or tr("unavailable")))}</div>', unsafe_allow_html=True)


def engine_status(data: Optional[Mapping[str, Mapping[str, Any]]]) -> None:
    """Render an accessible, compact health summary for external engines."""
    states = [
        ("osm_engine", bool(data and data["road"].get("available"))),
        ("rf_engine", bool(data and data["rf"].get("available"))),
        ("gee_engine", bool(data and data["gee"].get("available") and not data["gee"].get("fallback"))),
    ]
    if data is None:
        states = [("osm_engine", True), ("rf_engine", True), ("gee_engine", GEE_KEY.is_file())]
    items = "".join(
        f'<div class="engine"><span class="dot{"" if ready else " bad"}"></span>'
        f'{html.escape(tr(key))} · {html.escape(tr("online" if ready else "degraded"))}</div>'
        for key, ready in states
    )
    st.markdown(
        f'<div class="section">{html.escape(tr("engine_status"))}</div>'
        f'<div class="enginebar" role="status" aria-live="polite">{items}</div>',
        unsafe_allow_html=True,
    )


def terminal() -> None:
    section("terminal"); st.metric(tr("total"), len(st.session_state["target_points"]))
    if not st.session_state["target_points"]: st.info(tr("empty_table")); return
    labels = {"map": tr("map_click"), "upload": tr("file_upload"), "demo": tr("demo_source")}
    rows = [{tr("point"): index, tr("lat"): p["lat"], tr("lon"): p["lon"], tr("timestamp"): p.get("timestamp", tr("unavailable")), tr("source"): labels.get(p.get("source"), tr("unavailable"))} for index, p in enumerate(st.session_state["target_points"], 1)]
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True, column_config={tr("lat"): st.column_config.NumberColumn(format="%.6f"), tr("lon"): st.column_config.NumberColumn(format="%.6f")})


def main() -> None:
    initialize_state(); css()
    with st.sidebar:
        section("control")
        label_language = st.session_state.get("language", "EN")
        selected = st.radio(tr("language"), ["EN", "ZH"], index=0 if st.session_state["language"] == "EN" else 1,
                            format_func=lambda code, language=label_language: TEXT[language][code.lower()], key="language_radio")
        if selected != st.session_state["language"]: st.session_state["language"] = selected; st.rerun()
        section("ingest")
        upload = st.file_uploader(tr("upload"), type=["csv", "xlsx"], help=tr("upload_help"), key=f"upload_{st.session_state['upload_version']}")
        if upload is not None: ingest_file(upload)
        st.button(tr("demo_jakarta"), on_click=load_jakarta_demo, use_container_width=True, type="primary")
        st.button(tr("clear"), on_click=reset_state, use_container_width=True)
        st.caption(tr("capacity", used=len(st.session_state["target_points"]), maximum=MAX_POINTS))
    brand = html.escape(tr("brand"))
    st.markdown(f'<div class="head"><div><div class="brand">{brand[:4]}<span>{brand[4:]}</span></div><div class="sub">{html.escape(tr("subtitle"))}</div></div><div class="live">● {html.escape(tr("live"))}</div></div>', unsafe_allow_html=True)
    render_notices(); data = None
    if st.session_state["target_points"]:
        latest = st.session_state["target_points"][-1]
        with st.spinner(tr("loading")): data = run_analysis(latest["lat"], latest["lon"])
        if data["gee"].get("fallback"): st.warning(tr("gee_error"))
    engine_status(data)
    section("map", "map_desc")
    try:
        output = st_folium(build_map(data), height=590, returned_objects=["last_clicked"], use_container_width=True, key="omnisite_map")
        handle_click(output)
    except Exception as exc:
        LOGGER.exception("Map rendering failed: %s", exc)
        st.error(tr("map_error"))
    dashboard(data); terminal(); st.markdown(f'<div class="appfooter">{html.escape(tr("footer"))}</div>', unsafe_allow_html=True)


if __name__ == "__main__":
    main()