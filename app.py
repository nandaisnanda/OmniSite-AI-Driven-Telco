"""OmniSite: AI-Driven Telco Infrastructure Intelligence."""
from __future__ import annotations

import hashlib
import hmac
import html
import io
import json
import logging
import math
import os
import re
import time
from collections.abc import Mapping, Sequence
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import altair as alt
import ee
import folium
import osmnx as ox
import pandas as pd
import requests
import streamlit as st
from folium.plugins import Fullscreen
from shapely.geometry import Point
from streamlit_folium import st_folium
from streamlit_searchbox import st_searchbox

MAX_POINTS, CACHE_TTL = 100, 86_400
# Every cached engine result is held for a day. Without a ceiling the caches are keyed by
# coordinate and grow for as long as the process lives — 100 points per session across
# every visitor, entries that nothing ever evicts.
CACHE_MAX_ENTRIES = 512
# Nearest existing tower closer than this means sharing it beats building a new mast.
COLLOCATION_RADIUS_M = 400
# OpenCelliD rejects any BBOX over 4,000,000 sq.m, so the search box cannot be widened
# past a ~2 km square (2*span*111_320 <= 2000 m). That caps the reachable radius at ~1 km.
OPENCELLID_MAX_SPAN_DEG = 0.0089
OPENCELLID_SEARCH_KM = 1
MAX_UPLOAD_BYTES, MAX_UPLOAD_ROWS = 10 * 1024 * 1024, 10_000
DEFAULT_CENTER, DEFAULT_ZOOM = (-2.5489, 118.0148), 5
# Real coordinate exports rarely use the bare word. Headers arrive as "Latitude (WGS84)",
# "LAT_DEG", "Lintang", "Y" — the old exact-match-only pair rejected every one of them and
# reported the file as having no coordinates at all.
LAT_NAMES = {"lat", "lats", "latitude", "latitudes", "lattitude", "latitud",
             "lintang", "garislintang", "y", "ycoord", "coordy"}
LON_NAMES = {"lon", "lng", "long", "longitude", "longitudes", "longitud",
             "bujur", "garisbujur", "x", "xcoord", "coordx"}
COLORS = {"bg": "#0E1117", "panel": "#141922", "edge": "#263142", "text": "#F2F6FA",
          "muted": "#91A0B5", "cyan": "#00D4FF", "blue": "#249BFF", "red": "#FF4B64", "green": "#2ED47A"}
LAND_KEYS = {10: "trees", 20: "shrub", 30: "grass", 40: "crop", 50: "built", 60: "bare",
             70: "snow", 80: "water", 90: "wetland", 95: "mangrove", 100: "moss"}

EN = {
    "page": "OmniSite: AI-Driven Telco Infrastructure Intelligence", "subtitle": "AI-Driven Telco Infrastructure Intelligence",
    "brand": "OMNISITE", "live": "INTELLIGENCE ONLINE", "control": "CONTROL PANEL", "language": "Language", "en": "English", "zh": "Chinese Mandarin", "id": "Indonesian",
    "ingest": "DATA INGESTION", "upload": "Upload coordinates", "upload_help": "CSV or Excel containing latitude and longitude columns. Maximum 100 unique WGS84 points.",
    "location_search": "LOCATION SEARCH", "search_location": "Search place or address", "search_placeholder": "Type a mosque, university, restaurant, street...", "search_hint": "Type at least 3 characters and choose an OpenStreetMap suggestion. Selecting it focuses the map immediately.", "search_not_found": "No matching place was found.", "search_error": "OpenStreetMap location search is temporarily unavailable.", "search_found": "Map focused on: {location}",
    "demo_jakarta": "Load Jakarta Demo", "clear": "Clear All Points", "capacity": "Capacity {used}/{maximum}", "map": "GEOSPATIAL OPERATIONS CONSOLE",
    "map_desc": "Click the map to add a unique target point and run the intelligence pipeline.", "map_error": "The map could not be rendered. Please retry.",
    "legend": "MAP LEGEND", "target_legend": "Blue = Target Point", "bts_legend": "Red = Existing BTS", "built_legend": "Green = Built-up Area",
    "osm": "OpenStreetMap", "sat": "Esri World Imagery",
    "targets": "Target Points", "bts_layer": "Existing BTS", "built_layer": "Built-up Areas", "point": "Point",
    "lat": "Latitude", "lon": "Longitude", "target_tip": "Target Point {number}", "bts_tip": "Existing BTS {tower}", "built_tip": "Built-up Area",
    "dashboard": "EXECUTIVE INTELLIGENCE DASHBOARD", "dashboard_desc": "Cached multi-engine assessment for the latest target point.",
    "loading": "Running OSM, RF, and hybrid geospatial analysis…", "analysis_running": "Analysis is running in the background. You can continue using the map.", "analysis_failed": "Background analysis failed safely. Click another point to retry.", "rf": "RF Infrastructure", "deployment": "Deployment Status",
    "tower_distance": "Tower distance: {value}", "tower_id": "Tower ID: {value}", "terrain": "Terrain", "elevation": "Elevation",
    "meters": "{value} m", "slope": "Estimated slope: {value}°", "commercial": "Commercial", "population": "Population 500m",
    "cover": "Land cover: {value}", "access": "Accessibility", "road_distance": "Nearest Road Distance", "road_type": "Road type: {value}",
    "highway": "Highway tag: {value}", "unavailable": "Unavailable", "start": "Add a target point to activate the intelligence pipeline.",
    "no_road_value": "NO ROAD ACCESS", "no_road_hint": "No mapped road within 500 m",
    "recommend": "COVERAGE-GAP SITE FINDER",
    "recommend_desc": "Scans the area for places where measured population sits beyond the reach of any existing OpenCelliD tower, and ranks them by how many people are currently unserved.",
    "recommend_run": "Find candidate sites", "recommend_radius": "Search radius (km)",
    "recommend_spacing": "Grid spacing (km)", "recommend_count": "Candidates to return",
    "recommend_none": "No coverage gap found — every populated cell in this area already sits within {radius} m of a tower.",
    "recommend_failed": "Tower inventory unavailable (OpenCelliD quota or network). Refusing to rank sites without it — a missing inventory makes covered ground look like a gap.",
    "recommend_nokey": "OpenCelliD API key not configured, so existing towers cannot be checked.",
    "recommend_nogee": "Earth Engine is unavailable, so population demand cannot be measured. Refusing to rank sites on supply alone.",
    "recommend_nodemand": "Earth Engine accepted the request but returned no demand data. Try a smaller radius or retry shortly.",
    "recommend_toobig": "This search would evaluate {cells} grid cells, beyond the {maximum}-cell limit. Increase the grid spacing or reduce the radius.",
    "recommend_toowide": "Search radius too wide for the tower-inventory budget. Reduce the radius.",
    "recommend_estimate": "This search will evaluate {cells} grid cells and {tiles} tower lookups.",
    "recommend_stats": "Scanned {scanned} grid cells · {towers} towers inventoried",
    "unmet": "Unserved people", "nearest_tower": "Nearest tower", "candidate": "Candidate",
    "recommend_tip": "Proposed site {rank} · {people} unserved",
    "segmentation": "SITE SEGMENTATION (UNSUPERVISED ML)",
    "segmentation_desc": "K-means groups the analysed sites by measured ground conditions; Isolation Forest flags profiles that sit apart. Unsupervised by design — there is no ground-truth label for a good site, so nothing here is a trained prediction.",
    "segmentation_need": "Add and analyse at least {count} points to run segmentation.",
    "cluster": "Segment", "cluster_outlier": "Outlier", "cluster_size": "{count} sites",
    "silhouette": "Silhouette {value}", "clusters_found": "{k} segments · {features} features",
    "trait_high": "high {feature}", "trait_low": "low {feature}", "trait_average": "near batch average",
    "feat_elevation": "elevation", "feat_slope": "slope", "feat_population": "population",
    "feat_nightlight": "night-light", "feat_water": "surface water", "feat_poi": "POI density",
    "feat_power": "power distance", "feat_road": "road distance", "feat_gust": "wind gust",
    "feat_tower": "tower distance",
    "no_tower": "NO EXISTING TOWER", "no_tower_why": "OpenCelliD records no cell site within {radius} km — full greenfield build",
    "rf_no_key": "RF data unavailable — OpenCelliD API key not configured",
    "per_point": "PER-POINT ASSESSMENT", "per_point_desc": "Every target point scored individually. Select one to load its full intelligence panel.",
    "choose_point": "Select target point", "prev_point": "Previous point", "next_point": "Next point",
    "score": "Score", "verdict": "Verdict", "queued": "Queued…", "analysis_failed_short": "Failed",
    "verdict_approve": "APPROVE", "verdict_review": "REVIEW", "verdict_avoid": "AVOID", "verdict_insufficient": "NO DATA",
    "viewing_point": "Showing point {index} of {total}",
    "batch_progress": "Batch analysis: {done} of {total} points scored…",
    "manual_entry": "MANUAL COORDINATE", "add_point": "Add point", "manual_added": "Point added from manual entry.",
    "manual_hint": "Enter a WGS84 decimal coordinate to add a point without using the map. Negative latitude is south, negative longitude is west.",
    "remove_point": "Remove this point", "undo_remove": "Undo the last removal",
    "columns_seen": "Columns found in the file: {columns}. Supported names include lat / latitude / lintang / y and lon / lng / longitude / bujur / x.",
    "manual_source": "Manual Entry",
    "analysis_timeout": "Analysis exceeded the time budget and was abandoned. External engines are slow or unreachable — retry this point shortly.",
    "rate_limited": "Rate limit reached ({limit} per minute). Wait a moment before running this again.",
    "queue_full": "Analysis queue is full. Wait for the running points to finish, or clear some points.",
    "auth_required": "SIGN IN REQUIRED", "auth_password": "Access password", "auth_login": "Sign in",
    "auth_failed": "Incorrect password.",
    "auth_misconfigured": "AUTH_ENABLED is set but no APP_PASSWORD is configured. Refusing to start unprotected — set APP_PASSWORD in secrets, or set AUTH_ENABLED to false.",
    "auth_no_oidc": "AUTH_MODE is 'oidc' but this Streamlit build has no native OIDC support. Upgrade Streamlit or switch AUTH_MODE to 'session'.",
    "export_scorecard": "⬇ Export scorecard (CSV)", "export_candidates": "⬇ Export candidates (CSV)", "export_points": "⬇ Export points (CSV)",
    "partial": "Some external engines are unavailable. Available partial results are shown.",
    "read_error": "Unable to safely read {name}. Verify the file format and contents.", "columns_error": "No supported latitude/longitude columns were found in {name}.",
    "upload_large": "{name} exceeds the secure 10 MB upload limit.", "upload_type": "{name} is not a supported CSV or XLSX file.",
    "empty_upload": "No new valid coordinates were found in {name}.", "upload_ok": "Added {count} unique point(s) from {name}.",
    "skipped": "Skipped {count} invalid, duplicate, or excess record(s).", "limit": "The 100-point capacity has been reached.",
    "duplicate": "That coordinate is already registered.", "invalid": "The coordinate is outside the valid WGS84 range.",
    "terminal": "ENTERPRISE DATA TERMINAL", "total": "Total Points", "timestamp": "Timestamp (UTC)", "source": "Source",
    "map_click": "Map Click", "file_upload": "File Upload", "demo_source": "Jakarta Demo", "empty_table": "No coordinates registered.",
    "greenfield": "BUILD NEW TOWER", "collocation": "SHARE EXISTING TOWER", "unknown_road": "Unclassified",
    "greenfield_why": "Greenfield (build-to-suit) · nearest tower {distance}, beyond the {radius} m collocation radius",
    "collocation_why": "Collocation · nearest tower {distance}, within the {radius} m collocation radius",
    "rf_unknown_why": "No RF reference available for this point",
    "trees": "Trees", "shrub": "Shrubland", "grass": "Grassland", "crop": "Cropland", "built": "Built-up",
    "bare": "Bare / sparse vegetation", "snow": "Snow and ice", "water": "Permanent water", "wetland": "Herbaceous wetland",
    "mangrove": "Mangroves", "moss": "Moss and lichen", "unknown_land": "Unknown class ({code})",
    "engine_status": "ENGINE STATUS", "osm_engine": "OSM Roads", "rf_engine": "RF Intelligence", "gee_engine": "Geospatial Engine",
"online": "ONLINE", "degraded": "DEGRADED", "fallback": "HYBRID ONLINE", "configured": "AUTO READY", "mock_ready": "MOCK READY", "estimated": "Hybrid geospatial estimate", "not_checked": "NOT CHECKED",
    "feasibility": "SITE FEASIBILITY & RISK SCORECARD", "feasibility_desc": "Automated commercial, power, structural, environmental, and permitting screening.",
    "land_permit": "Land Cover & Permit", "permit_risk": "Permit Risk", "permit_low": "LOW", "permit_medium": "MEDIUM", "permit_high": "HIGH", "permit_restricted": "RESTRICTED", "permit_unknown": "NOT SCREENED",
    "land_value": "Cover: {value}", "permit_built": "Standard urban permitting expected", "permit_forest": "Forest permitting may be difficult and costly", "permit_water": "Water or wetland constraint detected", "permit_agri": "Land conversion review may be required", "permit_unscreened": "Land cover was not measured — permitting risk is unscreened, not low",
    "access_terrain": "Site Access & Terrain", "access_none": "NO ROAD ACCESS", "access_far": "ROAD ACCESS DISTANT", "access_near": "ROAD ACCESS OK", "access_unknown": "NOT SCREENED",
    "access_meta": "Nearest drivable road: {road}", "terrain_meta": "Ground slope: {slope}",
    "terrain_flat": "Flat ground — standard foundation", "terrain_moderate": "Moderate slope — extra civil works likely", "terrain_steep": "Steep ground — foundation and haulage cost multiplier", "terrain_unknown": "Slope was not measured",
    "access_none_note": "No mapped drivable road within 500 m — a new access route must be costed", "access_far_note": "Access road beyond 250 m — spur road required",
    "collocation_bonus": "Collocation credit applied — no new mast required",
    "power_access": "Electrification", "grid_connected": "GRID ACCESS LIKELY", "off_grid": "OFF-GRID RISK", "power_distance": "Nearest mapped power asset: {value}", "power_assets": "Mapped assets within 2 km: {value}",
    "offgrid_warning": "Off-Grid Zone: budget genset or solar power and additional OPEX.", "night_light": "Night-light radiance: {value}",
    "wind_hazard": "Structural & Wind", "max_gust": "10-year max gust", "wind_value": "{value} km/h", "tower_standard": "STANDARD TOWER", "tower_reinforced": "REINFORCED TOWER", "tower_heavy": "HEAVY-DUTY TOWER", "wind_source": "Historical daily maximum gust screening",
    "flood_risk": "Flood & Water Risk", "risk_low": "LOW RISK", "risk_medium": "MEDIUM RISK", "risk_high": "HIGH RISK", "risk_unknown": "NOT SCREENED", "water_distance": "Nearest mapped water feature: {value}", "water_occurrence": "Historical surface-water occurrence: {value}%", "flood_high_action": "Reject or elevate equipment platform; detailed hydrology survey required.", "flood_review": "Civil drainage and flood-level survey required.", "flood_clear": "No material flood indicator detected in desktop screening.",
    "market_poi": "Micro-POI Market", "poi_count": "Strategic POIs within 1 km", "poi_value": "{value} POIs", "poi_mix": "Schools {schools} · Universities {universities} · Hospitals {hospitals} · Markets {markets}", "market_high": "HIGH DATA-DEMAND POTENTIAL", "market_medium": "MODERATE MARKET POTENTIAL", "market_low": "LIMITED MAPPED POI DEMAND", "market_unknown": "NOT SCREENED",
    "site_score": "SITE FEASIBILITY SCORE", "score_value": "{value}/100", "recommendation": "Recommendation", "approve": "PROCEED TO SURVEY", "review": "CONDITIONAL REVIEW", "avoid": "AVOID / RELOCATE", "insufficient": "INSUFFICIENT DATA — NOT SCORED", "score_note": "Desktop screening only; confirm with field survey, permits, grid utility, geotechnical, and hydrology studies.",
    "confidence": "Screening coverage", "confidence_value": "{known}/{total} signals measured",
    "insufficient_note": "Only {known} of {total} screening signals could be measured, so no score is issued. An unmeasured constraint is not a passed constraint — retry when the engines recover.",
    "partial_signals": "{missing} screening signal(s) unmeasured; the verdict is capped at conditional review.",
    "data_live": "LIVE PUBLIC DATA", "data_hybrid": "HYBRID SCREENING", "not_mapped": "Not mapped", "kilometers": "{value} km",
    "footer": "WGS84 · GEE/Public Hybrid · Open-Meteo · OpenStreetMap · OpenCelliD-assisted RF intelligence",
}
ZH = {
    "page": "OmniSite：AI 驱动的电信基础设施智能平台", "subtitle": "AI 驱动的电信基础设施智能平台", "brand": "OMNISITE", "live": "智能引擎在线",
    "control": "控制面板", "language": "语言", "en": "英语", "zh": "中文（普通话）", "id": "印尼语", "ingest": "数据导入", "upload": "上传坐标", "demo_jakarta": "加载雅加达演示",
    "location_search": "位置搜索", "search_location": "搜索地点或地址", "search_placeholder": "输入清真寺、大学、餐厅、街道……", "search_hint": "输入至少 3 个字符并选择 OpenStreetMap 建议；选择后地图会立即定位。", "search_not_found": "未找到匹配的地点。", "search_error": "OpenStreetMap 位置搜索暂时不可用。", "search_found": "地图已定位至：{location}",
    "upload_help": "上传包含纬度和经度列的 CSV 或 Excel。最多 100 个唯一 WGS84 点位。", "clear": "清除所有点位", "capacity": "容量 {used}/{maximum}",
    "map": "地理空间作业控制台", "map_desc": "点击地图添加唯一目标点并运行智能分析管线。", "map_error": "无法渲染地图，请重试。",
    "legend": "地图图例", "target_legend": "蓝色 = 目标点", "bts_legend": "红色 = 现有基站", "built_legend": "绿色 = 建成区",
    "osm": "OpenStreetMap 地图", "sat": "Esri 世界影像",
    "targets": "目标点", "bts_layer": "现有基站", "built_layer": "建成区", "point": "点位", "lat": "纬度", "lon": "经度",
    "target_tip": "目标点 {number}", "bts_tip": "现有基站 {tower}", "built_tip": "建成区", "dashboard": "管理层智能仪表板",
    "dashboard_desc": "针对最新目标点的多引擎缓存评估。", "loading": "正在运行 OSM、射频和混合地理空间分析…", "analysis_running": "分析正在后台运行，您可以继续使用地图。", "analysis_failed": "后台分析已安全失败，请点击其他点位重试。",
    "rf": "射频基础设施", "deployment": "部署状态", "tower_distance": "基站距离：{value}", "tower_id": "基站编号：{value}",
    "terrain": "地形", "elevation": "海拔", "meters": "{value} 米", "slope": "估算坡度：{value}°", "commercial": "商业价值",
    "population": "500 米人口", "cover": "土地覆盖：{value}", "access": "可达性", "road_distance": "最近道路距离",
    "road_type": "道路类型：{value}", "highway": "公路标签：{value}", "unavailable": "不可用", "start": "添加目标点以启动智能分析管线。",
    "no_road_value": "无道路通达", "no_road_hint": "500 米内无已绘制道路",
    "recommend": "覆盖盲区选址",
    "recommend_desc": "扫描区域，找出实测人口位于所有既有 OpenCelliD 铁塔覆盖范围之外的位置，并按当前未被服务的人口数排序。",
    "recommend_run": "查找候选站址", "recommend_radius": "搜索半径（公里）",
    "recommend_spacing": "网格间距（公里）", "recommend_count": "返回候选数",
    "recommend_none": "未发现覆盖盲区 — 本区域内每个有人口的网格都已在铁塔 {radius} 米范围内。",
    "recommend_failed": "铁塔清单不可用（OpenCelliD 配额或网络问题）。缺少清单时拒绝排序 — 否则已覆盖区域会被误判为盲区。",
    "recommend_nokey": "未配置 OpenCelliD 密钥，无法核查既有铁塔。",
    "recommend_nogee": "Earth Engine 不可用，无法实测人口需求。拒绝仅凭供给侧数据排序站址。",
    "recommend_nodemand": "Earth Engine 已受理请求但未返回需求数据。请缩小半径或稍后重试。",
    "recommend_toobig": "本次搜索需评估 {cells} 个网格，超出 {maximum} 个上限。请增大网格间距或缩小半径。",
    "recommend_toowide": "搜索半径超出铁塔清单查询预算，请缩小半径。",
    "recommend_estimate": "本次搜索将评估 {cells} 个网格与 {tiles} 次铁塔查询。",
    "recommend_stats": "已扫描 {scanned} 个网格 · 已清点 {towers} 座铁塔",
    "unmet": "未服务人口", "nearest_tower": "最近铁塔", "candidate": "候选",
    "recommend_tip": "建议站址 {rank} · 未服务 {people} 人",
    "segmentation": "站址分群（无监督机器学习）",
    "segmentation_desc": "K-means 依据实测地面条件对已分析站址分群，Isolation Forest 标记异常剖面。刻意采用无监督方法——优质站址没有真实标签，因此这里没有任何训练出的预测。",
    "segmentation_need": "至少添加并分析 {count} 个点后才能运行分群。",
    "cluster": "分群", "cluster_outlier": "异常", "cluster_size": "{count} 个站址",
    "silhouette": "轮廓系数 {value}", "clusters_found": "{k} 个分群 · {features} 个特征",
    "trait_high": "高{feature}", "trait_low": "低{feature}", "trait_average": "接近批次均值",
    "feat_elevation": "海拔", "feat_slope": "坡度", "feat_population": "人口",
    "feat_nightlight": "夜间灯光", "feat_water": "地表水", "feat_poi": "POI 密度",
    "feat_power": "电力距离", "feat_road": "道路距离", "feat_gust": "阵风",
    "feat_tower": "铁塔距离",
    "no_tower": "无既有铁塔", "no_tower_why": "OpenCelliD 在 {radius} 公里内无基站记录 — 完全新建站址",
    "rf_no_key": "射频数据不可用 — 未配置 OpenCelliD 密钥",
    "per_point": "逐点评估", "per_point_desc": "每个目标点单独评分。选择其一以加载完整智能面板。",
    "choose_point": "选择目标点", "prev_point": "上一个点", "next_point": "下一个点",
    "score": "评分", "verdict": "结论", "queued": "排队中…", "analysis_failed_short": "失败",
    "verdict_approve": "批准", "verdict_review": "复核", "verdict_avoid": "回避", "verdict_insufficient": "无数据",
    "viewing_point": "正在显示第 {index} / {total} 个点",
    "batch_progress": "批量分析：已完成 {done} / {total} 个点…",
    "manual_entry": "手动输入坐标", "add_point": "添加点位", "manual_added": "已通过手动输入添加点位。",
    "manual_hint": "输入 WGS84 十进制坐标即可不使用地图添加点位。纬度为负表示南纬，经度为负表示西经。",
    "remove_point": "删除该点位", "undo_remove": "撤销上一次删除",
    "columns_seen": "文件中找到的列：{columns}。支持的列名包括 lat / latitude / lintang / y 以及 lon / lng / longitude / bujur / x。",
    "manual_source": "手动输入",
    "analysis_timeout": "分析超出时间预算并已放弃。外部引擎缓慢或不可达 — 请稍后重试该点位。",
    "rate_limited": "已达到频率上限（每分钟 {limit} 次）。请稍候再运行。",
    "queue_full": "分析队列已满。请等待进行中的点位完成，或清除部分点位。",
    "auth_required": "需要登录", "auth_password": "访问密码", "auth_login": "登录",
    "auth_failed": "密码错误。",
    "auth_misconfigured": "已启用 AUTH_ENABLED 但未配置 APP_PASSWORD。拒绝在无保护状态下启动 — 请在 secrets 中设置 APP_PASSWORD，或将 AUTH_ENABLED 设为 false。",
    "auth_no_oidc": "AUTH_MODE 设为 'oidc'，但当前 Streamlit 版本不支持原生 OIDC。请升级 Streamlit 或将 AUTH_MODE 改为 'session'。",
    "export_scorecard": "⬇ 导出评分表（CSV）", "export_candidates": "⬇ 导出候选站址（CSV）", "export_points": "⬇ 导出点位（CSV）",
    "partial": "部分外部引擎不可用，现显示可用的部分结果。",
    "read_error": "无法安全读取 {name}，请检查文件格式和内容。", "columns_error": "在 {name} 中未找到支持的纬度/经度列。", "empty_upload": "在 {name} 中未找到新的有效坐标。",
    "upload_large": "{name} 超过安全的 10 MB 上传限制。", "upload_type": "{name} 不是受支持的 CSV 或 XLSX 文件。",
    "upload_ok": "已从 {name} 添加 {count} 个唯一点位。", "skipped": "已跳过 {count} 条无效、重复或超额记录。",
    "limit": "已达到 100 个点位的容量上限。", "duplicate": "该坐标已登记。", "invalid": "坐标超出有效 WGS84 范围。",
    "terminal": "企业数据终端", "total": "点位总数", "timestamp": "时间戳（UTC）", "source": "来源", "map_click": "地图点击",
    "file_upload": "文件上传", "demo_source": "雅加达演示", "empty_table": "尚未登记坐标。", "greenfield": "新建铁塔", "collocation": "共用现有铁塔", "unknown_road": "未分类",
    "greenfield_why": "新建站址（定制建设）· 最近铁塔 {distance}，超出 {radius} 米共址半径",
    "collocation_why": "共址 · 最近铁塔 {distance}，在 {radius} 米共址半径内",
    "rf_unknown_why": "此点无可用射频参考",
    "trees": "乔木", "shrub": "灌木地", "grass": "草地", "crop": "农田", "built": "建成区", "bare": "裸地 / 稀疏植被",
    "snow": "冰雪", "water": "永久水体", "wetland": "草本湿地", "mangrove": "红树林", "moss": "苔藓和地衣",
    "unknown_land": "未知类别（{code}）", "engine_status": "引擎状态", "osm_engine": "OSM 道路", "rf_engine": "射频智能",
"gee_engine": "地理空间引擎", "online": "在线", "degraded": "降级", "fallback": "混合在线", "configured": "自动就绪", "mock_ready": "模拟就绪", "estimated": "混合地理空间估算", "not_checked": "未检查",
    "feasibility": "站址可行性与风险评分卡", "feasibility_desc": "自动化商业、电力、结构、环境和许可初筛。",
    "land_permit": "土地覆盖与许可", "permit_risk": "许可风险", "permit_low": "低", "permit_medium": "中", "permit_high": "高", "permit_restricted": "受限", "permit_unknown": "未筛查",
    "land_value": "覆盖类型：{value}", "permit_built": "预计采用标准城市许可流程", "permit_forest": "林地许可可能困难且成本高", "permit_water": "检测到水体或湿地限制", "permit_agri": "可能需要土地用途变更审查", "permit_unscreened": "未实测土地覆盖 — 许可风险属于未筛查，而非低风险",
    "access_terrain": "站址通达与地形", "access_none": "无道路通达", "access_far": "道路通达偏远", "access_near": "道路通达良好", "access_unknown": "未筛查",
    "access_meta": "最近可行车道路：{road}", "terrain_meta": "地面坡度：{slope}",
    "terrain_flat": "地势平坦 — 标准基础", "terrain_moderate": "中等坡度 — 可能需要额外土建", "terrain_steep": "地势陡峭 — 基础与运输成本倍增", "terrain_unknown": "未实测坡度",
    "access_none_note": "500 米内无已绘制的可行车道路 — 须计入新建进场道路成本", "access_far_note": "进场道路超过 250 米 — 需要修建支线道路",
    "collocation_bonus": "已计入共址加分 — 无需新建铁塔",
    "power_access": "电力接入", "grid_connected": "可能具备电网接入", "off_grid": "离网风险", "power_distance": "最近已绘制电力设施：{value}", "power_assets": "2 公里内已绘制设施：{value}",
    "offgrid_warning": "离网区域：需为发电机或太阳能及额外运维成本编制预算。", "night_light": "夜间灯光辐亮度：{value}",
    "wind_hazard": "结构与风害", "max_gust": "十年最大阵风", "wind_value": "{value} 公里/小时", "tower_standard": "标准塔型", "tower_reinforced": "加强型塔", "tower_heavy": "重型塔", "wind_source": "历史逐日最大阵风初筛",
    "flood_risk": "洪水与水体风险", "risk_low": "低风险", "risk_medium": "中风险", "risk_high": "高风险", "risk_unknown": "未筛查", "water_distance": "最近已绘制水体：{value}", "water_occurrence": "历史地表水出现率：{value}%", "flood_high_action": "建议拒绝或抬高设备平台；必须开展详细水文调查。", "flood_review": "需要开展排水和洪水位调查。", "flood_clear": "桌面筛查未发现重大洪水指标。",
    "market_poi": "微观兴趣点市场", "poi_count": "1 公里内战略兴趣点", "poi_value": "{value} 个兴趣点", "poi_mix": "学校 {schools} · 大学 {universities} · 医院 {hospitals} · 市场 {markets}", "market_high": "高数据需求潜力", "market_medium": "中等市场潜力", "market_low": "已绘制兴趣点需求有限", "market_unknown": "未筛查",
    "site_score": "站址可行性得分", "score_value": "{value}/100", "recommendation": "建议", "approve": "进入现场勘察", "review": "有条件审查", "avoid": "避开 / 迁址", "insufficient": "数据不足 — 未评分", "score_note": "仅用于桌面初筛；须通过现场、许可、电网、岩土和水文调查确认。",
    "confidence": "筛查覆盖度", "confidence_value": "已实测 {known}/{total} 项信号",
    "insufficient_note": "{total} 项筛查信号中仅实测到 {known} 项，因此不出具评分。未实测的约束不等于已通过的约束 — 请在引擎恢复后重试。",
    "partial_signals": "有 {missing} 项筛查信号未实测，结论上限为有条件审查。",
    "data_live": "实时公共数据", "data_hybrid": "混合初筛", "not_mapped": "未绘制", "kilometers": "{value} 公里",
    "footer": "WGS84 · GEE/公共数据混合 · Open-Meteo · OpenStreetMap · OpenCelliD 辅助射频智能",
}
ID = {
    "page": "OmniSite: Intelijen Infrastruktur Telko Berbasis AI", "subtitle": "Intelijen Infrastruktur Telko Berbasis AI",
    "brand": "OMNISITE", "live": "INTELIJEN AKTIF", "control": "PANEL KENDALI", "language": "Bahasa", "en": "Inggris", "zh": "Mandarin", "id": "Indonesia",
    "ingest": "MASUKAN DATA", "upload": "Unggah koordinat", "upload_help": "CSV atau Excel berisi kolom lintang dan bujur. Maksimum 100 titik WGS84 unik.",
    "location_search": "PENCARIAN LOKASI", "search_location": "Cari tempat atau alamat", "search_placeholder": "Ketik masjid, universitas, restoran, jalan...", "search_hint": "Ketik minimal 3 karakter lalu pilih saran OpenStreetMap. Memilihnya langsung memfokuskan peta.", "search_not_found": "Tidak ada tempat yang cocok.", "search_error": "Pencarian lokasi OpenStreetMap sedang tidak tersedia.", "search_found": "Peta difokuskan ke: {location}",
    "demo_jakarta": "Muat Demo Jakarta", "clear": "Hapus Semua Titik", "capacity": "Kapasitas {used}/{maximum}", "map": "KONSOL OPERASI GEOSPASIAL",
    "map_desc": "Klik peta untuk menambah titik target unik dan menjalankan pipeline intelijen.", "map_error": "Peta gagal dirender. Silakan coba lagi.",
    "legend": "LEGENDA PETA", "target_legend": "Biru = Titik Target", "bts_legend": "Merah = BTS Eksisting", "built_legend": "Hijau = Area Terbangun",
    "osm": "OpenStreetMap", "sat": "Esri World Imagery",
    "targets": "Titik Target", "bts_layer": "BTS Eksisting", "built_layer": "Area Terbangun", "point": "Titik",
    "lat": "Lintang", "lon": "Bujur", "target_tip": "Titik Target {number}", "bts_tip": "BTS Eksisting {tower}", "built_tip": "Area Terbangun",
    "dashboard": "DASBOR INTELIJEN EKSEKUTIF", "dashboard_desc": "Penilaian multi-mesin tercache untuk titik target terkini.",
    "loading": "Menjalankan analisis OSM, RF, dan geospasial hibrida…", "analysis_running": "Analisis berjalan di latar belakang. Anda dapat terus menggunakan peta.", "analysis_failed": "Analisis latar belakang gagal dengan aman. Klik titik lain untuk mencoba lagi.", "rf": "Infrastruktur RF", "deployment": "Status Penggelaran",
    "tower_distance": "Jarak menara: {value}", "tower_id": "ID menara: {value}", "terrain": "Medan", "elevation": "Elevasi",
    "meters": "{value} m", "slope": "Perkiraan kemiringan: {value}°", "commercial": "Komersial", "population": "Populasi 500 m",
    "cover": "Tutupan lahan: {value}", "access": "Aksesibilitas", "road_distance": "Jarak Jalan Terdekat", "road_type": "Jenis jalan: {value}",
    "highway": "Tag highway: {value}", "unavailable": "Tidak tersedia", "start": "Tambahkan titik target untuk mengaktifkan pipeline intelijen.",
    "no_road_value": "TANPA AKSES JALAN", "no_road_hint": "Tidak ada jalan terpetakan dalam 500 m",
    "recommend": "PENCARI LOKASI CELAH CAKUPAN",
    "recommend_desc": "Memindai area untuk mencari lokasi yang populasinya terukur berada di luar jangkauan menara OpenCelliD mana pun, lalu memeringkatnya berdasarkan jumlah penduduk yang belum terlayani.",
    "recommend_run": "Cari lokasi kandidat", "recommend_radius": "Radius pencarian (km)",
    "recommend_spacing": "Jarak antar grid (km)", "recommend_count": "Jumlah kandidat",
    "recommend_none": "Tidak ditemukan celah cakupan — setiap sel berpenduduk di area ini sudah berada dalam {radius} m dari sebuah menara.",
    "recommend_failed": "Inventaris menara tidak tersedia (kuota OpenCelliD atau jaringan). Menolak memeringkat lokasi tanpanya — inventaris yang tidak lengkap membuat area yang sudah tercakup tampak sebagai celah.",
    "recommend_nokey": "Kunci API OpenCelliD belum dikonfigurasi, sehingga menara eksisting tidak dapat diperiksa.",
    "recommend_nogee": "Earth Engine tidak tersedia, sehingga permintaan populasi tidak dapat diukur. Menolak memeringkat lokasi hanya berdasarkan sisi pasokan.",
    "recommend_nodemand": "Earth Engine menerima permintaan tetapi tidak mengembalikan data permintaan. Coba radius lebih kecil atau ulangi sebentar lagi.",
    "recommend_toobig": "Pencarian ini akan mengevaluasi {cells} sel grid, melampaui batas {maximum} sel. Perbesar jarak antar grid atau perkecil radius.",
    "recommend_toowide": "Radius pencarian terlalu lebar untuk anggaran inventaris menara. Perkecil radius.",
    "recommend_estimate": "Pencarian ini akan mengevaluasi {cells} sel grid dan {tiles} kueri menara.",
    "recommend_stats": "{scanned} sel grid dipindai · {towers} menara terinventarisasi",
    "unmet": "Penduduk belum terlayani", "nearest_tower": "Menara terdekat", "candidate": "Kandidat",
    "recommend_tip": "Usulan lokasi {rank} · {people} belum terlayani",
    "segmentation": "SEGMENTASI LOKASI (ML TANPA SUPERVISI)",
    "segmentation_desc": "K-means mengelompokkan lokasi yang telah dianalisis berdasarkan kondisi lapangan terukur; Isolation Forest menandai profil yang menyimpang. Sengaja tanpa supervisi — tidak ada label kebenaran untuk lokasi yang baik, jadi tidak ada prediksi terlatih di sini.",
    "segmentation_need": "Tambahkan dan analisis minimal {count} titik untuk menjalankan segmentasi.",
    "cluster": "Segmen", "cluster_outlier": "Pencilan", "cluster_size": "{count} lokasi",
    "silhouette": "Silhouette {value}", "clusters_found": "{k} segmen · {features} fitur",
    "trait_high": "{feature} tinggi", "trait_low": "{feature} rendah", "trait_average": "mendekati rata-rata batch",
    "feat_elevation": "elevasi", "feat_slope": "kemiringan", "feat_population": "populasi",
    "feat_nightlight": "cahaya malam", "feat_water": "air permukaan", "feat_poi": "kepadatan POI",
    "feat_power": "jarak listrik", "feat_road": "jarak jalan", "feat_gust": "hembusan angin",
    "feat_tower": "jarak menara",
    "no_tower": "TIDAK ADA MENARA EKSISTING", "no_tower_why": "OpenCelliD tidak mencatat sel apa pun dalam {radius} km — pembangunan greenfield penuh",
    "rf_no_key": "Data RF tidak tersedia — kunci API OpenCelliD belum dikonfigurasi",
    "per_point": "PENILAIAN PER TITIK", "per_point_desc": "Setiap titik target dinilai satu per satu. Pilih salah satu untuk memuat panel intelijen lengkapnya.",
    "choose_point": "Pilih titik target", "prev_point": "Titik sebelumnya", "next_point": "Titik berikutnya",
    "score": "Skor", "verdict": "Kesimpulan", "queued": "Antre…", "analysis_failed_short": "Gagal",
    "verdict_approve": "SETUJU", "verdict_review": "TINJAU", "verdict_avoid": "HINDARI", "verdict_insufficient": "TANPA DATA",
    "viewing_point": "Menampilkan titik {index} dari {total}",
    "batch_progress": "Analisis batch: {done} dari {total} titik telah dinilai…",
    "manual_entry": "KOORDINAT MANUAL", "add_point": "Tambah titik", "manual_added": "Titik ditambahkan dari input manual.",
    "manual_hint": "Masukkan koordinat desimal WGS84 untuk menambah titik tanpa peta. Lintang negatif berarti selatan, bujur negatif berarti barat.",
    "remove_point": "Hapus titik ini", "undo_remove": "Batalkan penghapusan terakhir",
    "columns_seen": "Kolom yang ditemukan pada berkas: {columns}. Nama yang didukung antara lain lat / latitude / lintang / y dan lon / lng / longitude / bujur / x.",
    "manual_source": "Input Manual",
    "analysis_timeout": "Analisis melewati anggaran waktu dan dihentikan. Mesin eksternal lambat atau tidak terjangkau — coba lagi titik ini sebentar lagi.",
    "rate_limited": "Batas laju tercapai ({limit} per menit). Tunggu sejenak sebelum menjalankannya lagi.",
    "queue_full": "Antrean analisis penuh. Tunggu titik yang sedang berjalan selesai, atau hapus sebagian titik.",
    "auth_required": "PERLU MASUK", "auth_password": "Kata sandi akses", "auth_login": "Masuk",
    "auth_failed": "Kata sandi salah.",
    "auth_misconfigured": "AUTH_ENABLED aktif tetapi APP_PASSWORD belum dikonfigurasi. Menolak berjalan tanpa proteksi — atur APP_PASSWORD di secrets, atau setel AUTH_ENABLED ke false.",
    "auth_no_oidc": "AUTH_MODE bernilai 'oidc' tetapi build Streamlit ini tidak mendukung OIDC bawaan. Perbarui Streamlit atau ubah AUTH_MODE ke 'session'.",
    "export_scorecard": "⬇ Ekspor kartu skor (CSV)", "export_candidates": "⬇ Ekspor kandidat (CSV)", "export_points": "⬇ Ekspor titik (CSV)",
    "partial": "Sebagian mesin eksternal tidak tersedia. Hasil parsial yang tersedia ditampilkan.",
    "read_error": "Tidak dapat membaca {name} dengan aman. Periksa format dan isi berkas.", "columns_error": "Tidak ditemukan kolom lintang/bujur yang didukung pada {name}.",
    "upload_large": "{name} melampaui batas unggah aman 10 MB.", "upload_type": "{name} bukan berkas CSV atau XLSX yang didukung.",
    "empty_upload": "Tidak ditemukan koordinat valid baru pada {name}.", "upload_ok": "Menambahkan {count} titik unik dari {name}.",
    "skipped": "Melewati {count} data tidak valid, duplikat, atau berlebih.", "limit": "Kapasitas 100 titik telah tercapai.",
    "duplicate": "Koordinat tersebut sudah terdaftar.", "invalid": "Koordinat berada di luar rentang WGS84 yang valid.",
    "terminal": "TERMINAL DATA ENTERPRISE", "total": "Total Titik", "timestamp": "Waktu (UTC)", "source": "Sumber",
    "map_click": "Klik Peta", "file_upload": "Unggah Berkas", "demo_source": "Demo Jakarta", "empty_table": "Belum ada koordinat terdaftar.",
    "greenfield": "BANGUN MENARA BARU", "collocation": "BERBAGI MENARA EKSISTING", "unknown_road": "Tidak terklasifikasi",
    "greenfield_why": "Greenfield (bangun sesuai kebutuhan) · menara terdekat {distance}, melampaui radius kolokasi {radius} m",
    "collocation_why": "Kolokasi · menara terdekat {distance}, dalam radius kolokasi {radius} m",
    "rf_unknown_why": "Tidak ada referensi RF untuk titik ini",
    "trees": "Pepohonan", "shrub": "Semak belukar", "grass": "Padang rumput", "crop": "Lahan pertanian", "built": "Terbangun",
    "bare": "Lahan gundul / vegetasi jarang", "snow": "Salju dan es", "water": "Perairan permanen", "wetland": "Lahan basah herba",
    "mangrove": "Mangrove", "moss": "Lumut dan liken", "unknown_land": "Kelas tidak dikenal ({code})",
    "engine_status": "STATUS MESIN", "osm_engine": "Jalan OSM", "rf_engine": "Intelijen RF", "gee_engine": "Mesin Geospasial",
"online": "AKTIF", "degraded": "TERDEGRADASI", "fallback": "HIBRIDA AKTIF", "configured": "SIAP OTOMATIS", "mock_ready": "SIAP MOCK", "estimated": "Estimasi geospasial hibrida", "not_checked": "BELUM DIPERIKSA",
    "feasibility": "KARTU SKOR KELAYAKAN & RISIKO LOKASI", "feasibility_desc": "Penyaringan otomatis aspek komersial, kelistrikan, struktural, lingkungan, dan perizinan.",
    "land_permit": "Tutupan Lahan & Izin", "permit_risk": "Risiko Izin", "permit_low": "RENDAH", "permit_medium": "SEDANG", "permit_high": "TINGGI", "permit_restricted": "TERBATAS", "permit_unknown": "BELUM DISARING",
    "land_value": "Tutupan: {value}", "permit_built": "Perizinan perkotaan standar diperkirakan berlaku", "permit_forest": "Perizinan kawasan hutan berpotensi sulit dan mahal", "permit_water": "Terdeteksi kendala perairan atau lahan basah", "permit_agri": "Kemungkinan diperlukan kajian alih fungsi lahan", "permit_unscreened": "Tutupan lahan tidak terukur — risiko izin berstatus belum disaring, bukan rendah",
    "access_terrain": "Akses Lokasi & Medan", "access_none": "TANPA AKSES JALAN", "access_far": "AKSES JALAN JAUH", "access_near": "AKSES JALAN MEMADAI", "access_unknown": "BELUM DISARING",
    "access_meta": "Jalan terdekat yang dapat dilalui: {road}", "terrain_meta": "Kemiringan tanah: {slope}",
    "terrain_flat": "Tanah datar — fondasi standar", "terrain_moderate": "Kemiringan sedang — kemungkinan pekerjaan sipil tambahan", "terrain_steep": "Tanah curam — pengganda biaya fondasi dan pengangkutan", "terrain_unknown": "Kemiringan tidak terukur",
    "access_none_note": "Tidak ada jalan terpetakan yang dapat dilalui dalam 500 m — biaya jalan akses baru harus diperhitungkan", "access_far_note": "Jalan akses lebih dari 250 m — diperlukan jalan cabang",
    "collocation_bonus": "Kredit kolokasi diterapkan — tidak perlu menara baru",
    "power_access": "Kelistrikan", "grid_connected": "AKSES JARINGAN LISTRIK MEMUNGKINKAN", "off_grid": "RISIKO DI LUAR JARINGAN", "power_distance": "Aset listrik terpetakan terdekat: {value}", "power_assets": "Aset terpetakan dalam 2 km: {value}",
    "offgrid_warning": "Zona luar jaringan: anggarkan genset atau tenaga surya beserta OPEX tambahan.", "night_light": "Radiansi cahaya malam: {value}",
    "wind_hazard": "Struktur & Angin", "max_gust": "Hembusan maksimum 10 tahun", "wind_value": "{value} km/jam", "tower_standard": "MENARA STANDAR", "tower_reinforced": "MENARA DIPERKUAT", "tower_heavy": "MENARA BERAT", "wind_source": "Penyaringan hembusan angin maksimum harian historis",
    "flood_risk": "Risiko Banjir & Air", "risk_low": "RISIKO RENDAH", "risk_medium": "RISIKO SEDANG", "risk_high": "RISIKO TINGGI", "risk_unknown": "BELUM DISARING", "water_distance": "Fitur perairan terpetakan terdekat: {value}", "water_occurrence": "Kemunculan air permukaan historis: {value}%", "flood_high_action": "Tolak atau tinggikan platform peralatan; survei hidrologi rinci wajib dilakukan.", "flood_review": "Diperlukan survei drainase sipil dan muka air banjir.", "flood_clear": "Tidak ada indikator banjir signifikan pada penyaringan meja.",
    "market_poi": "Pasar Mikro-POI", "poi_count": "POI strategis dalam 1 km", "poi_value": "{value} POI", "poi_mix": "Sekolah {schools} · Universitas {universities} · Rumah sakit {hospitals} · Pasar {markets}", "market_high": "POTENSI PERMINTAAN DATA TINGGI", "market_medium": "POTENSI PASAR SEDANG", "market_low": "PERMINTAAN POI TERPETAKAN TERBATAS", "market_unknown": "BELUM DISARING",
    "site_score": "SKOR KELAYAKAN LOKASI", "score_value": "{value}/100", "recommendation": "Rekomendasi", "approve": "LANJUT KE SURVEI", "review": "TINJAUAN BERSYARAT", "avoid": "HINDARI / RELOKASI", "insufficient": "DATA TIDAK CUKUP — TIDAK DINILAI", "score_note": "Penyaringan meja saja; konfirmasi dengan survei lapangan, perizinan, utilitas jaringan listrik, geoteknik, dan studi hidrologi.",
    "confidence": "Cakupan penyaringan", "confidence_value": "{known}/{total} sinyal terukur",
    "insufficient_note": "Hanya {known} dari {total} sinyal penyaringan yang dapat diukur, sehingga tidak ada skor yang diterbitkan. Kendala yang tidak terukur bukan berarti kendala yang lolos — coba lagi setelah mesin pulih.",
    "partial_signals": "{missing} sinyal penyaringan tidak terukur; kesimpulan dibatasi hingga tinjauan bersyarat.",
    "data_live": "DATA PUBLIK LANGSUNG", "data_hybrid": "PENYARINGAN HIBRIDA", "not_mapped": "Tidak terpetakan", "kilometers": "{value} km",
    "footer": "WGS84 · Hibrida GEE/Publik · Open-Meteo · OpenStreetMap · Intelijen RF dibantu OpenCelliD",
}
TEXT = {"EN": EN, "ZH": ZH, "ID": ID}

st.set_page_config(page_title=EN["page"], page_icon="📡", layout="wide", initial_sidebar_state="expanded")
LOGGER = logging.getLogger("omnisite")


def configure_logging() -> None:
    """Attach a handler once so degradation diagnostics actually reach an operator.

    Without this the module-level logger inherits the root default of WARNING with no
    handler, so every LOGGER.info about a dead Overpass mirror, a refused OpenCelliD
    lookup or a failed Earth Engine init was written and then discarded. The app looked
    healthy while running entirely on fallbacks.
    """
    if LOGGER.handlers:
        return
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)-7s %(name)s [%(threadName)s] %(message)s"))
    LOGGER.addHandler(handler)
    LOGGER.setLevel(os.getenv("OMNISITE_LOG_LEVEL", "INFO").upper())
    LOGGER.propagate = False


configure_logging()


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


def secure_int(name: str, default: int, minimum: int = 1) -> int:
    """Resolve a numeric setting, falling back rather than crashing on a bad value."""
    try:
        return max(minimum, int(float(secure_setting(name, str(default)))))
    except (TypeError, ValueError):
        LOGGER.warning("Setting %s is not a number; using %s", name, default)
        return default


def secure_flag(name: str, default: bool = False) -> bool:
    return secure_setting(name, "true" if default else "false").strip().lower() in {"1", "true", "yes", "on"}


OPENCELLID_KEY = secure_setting("OPENCELLID_API_KEY")
GEE_KEY = Path(secure_setting("GEE_SERVICE_ACCOUNT_FILE", "apigee.json")).expanduser()

# These four settings were documented in secrets.toml.example as "required for
# production" while nothing in the app read them, so every deployment ran wide open and
# any visitor could spend the operator's OpenCelliD and Earth Engine quota.
AUTH_ENABLED = secure_flag("AUTH_ENABLED")
AUTH_MODE = secure_setting("AUTH_MODE", "session").strip().lower()
APP_PASSWORD = secure_setting("APP_PASSWORD")
RATE_LIMIT_ANALYSIS = secure_int("RATE_LIMIT_ANALYSIS_PER_MINUTE", 10)
RATE_LIMIT_RECOMMEND = secure_int("RATE_LIMIT_RECOMMEND_PER_MINUTE", 3)
MAX_QUEUED_JOBS = secure_int("MAX_QUEUED_JOBS", 50)
# A cold ten-year wind archive request alone can take 45 s, so the whole five-engine
# pipeline needs materially more headroom than that before it is declared stuck.
JOB_TIMEOUT_SECONDS = secure_int("JOB_TIMEOUT_SECONDS", 150, minimum=30)


def rate_limited(action: str, per_minute: int) -> bool:
    """True when this session has already spent its budget for `action` this minute.

    Every guarded action costs someone else's quota — OpenCelliD lookups, Earth Engine
    compute, Overpass queries — so the ceiling is per session and enforced before the
    work is submitted, not after it has already been paid for.
    """
    now = time.monotonic()
    window = st.session_state.setdefault("rate_windows", {}).setdefault(action, [])
    window[:] = [stamp for stamp in window if now - stamp < 60]
    if len(window) >= per_minute:
        return True
    window.append(now)
    return False


def require_authentication() -> bool:
    """Gate the app when AUTH_ENABLED is set. Returns True when the visitor may proceed."""
    if not AUTH_ENABLED:
        return True
    if AUTH_MODE == "oidc":
        # Streamlit ships a real OIDC flow; reimplementing one here would be strictly
        # worse. If this build has no st.login, refuse rather than silently serve open.
        if not hasattr(st, "login"):
            st.error(tr("auth_no_oidc"))
            return False
        if not getattr(getattr(st, "user", None), "is_logged_in", False):
            st.warning(tr("auth_required"))
            st.button(tr("auth_login"), on_click=st.login, type="primary")
            return False
        return True
    if not APP_PASSWORD:
        # Failing closed is the only safe reading of "auth enabled but no credential".
        st.error(tr("auth_misconfigured"))
        return False
    if st.session_state.get("authenticated"):
        return True
    st.markdown(f'<div class="section">{html.escape(tr("auth_required"))}</div>', unsafe_allow_html=True)
    with st.form("omnisite_auth"):
        supplied = st.text_input(tr("auth_password"), type="password")
        if st.form_submit_button(tr("auth_login"), type="primary"):
            # compare_digest keeps the check constant-time so the shared secret cannot
            # be recovered one character at a time.
            if hmac.compare_digest(supplied, APP_PASSWORD):
                st.session_state["authenticated"] = True
                st.rerun()
            LOGGER.warning("Rejected authentication attempt")
            st.error(tr("auth_failed"))
    return False


def tr(key: str, **values: Any) -> str:
    template = TEXT.get(st.session_state.get("language", "EN"), EN).get(key, EN.get(key, key))
    return template.format(**values) if values else template


def initialize_state() -> None:
    defaults: dict[str, Any] = {"target_points": [], "language": "EN", "last_click": None, "upload_hashes": set(),
                "upload_version": 0, "notices": [], "analysis_jobs": {}, "analysis_started": {},
                 "analysis_results": {}, "analysis_failures": {}, "map_view": None,
                 "location_candidates": [], "map_revision": 0, "selected_point": None,
                 "recommendations": None, "rate_windows": {}}
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value
    if not isinstance(st.session_state["target_points"], list):
        st.session_state["target_points"] = []
    st.session_state["target_points"] = st.session_state["target_points"][:MAX_POINTS]


# Interface preferences are not data. Wiping them made "Clear All Points" silently
# reset the operator's language to English and drop the search box they were using.
PRESERVED_ON_CLEAR = ("language", "language_radio", "active_location_identity")


def reset_state() -> None:
    """Clear target points and every result derived from them, keeping preferences."""
    keep = {key: st.session_state[key] for key in PRESERVED_ON_CLEAR if key in st.session_state}
    for future in st.session_state.get("analysis_jobs", {}).values():
        future.cancel()
    for key in list(st.session_state):
        del st.session_state[key]
    for key, value in keep.items():
        st.session_state[key] = value
    initialize_state()


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


def coord_key(lat: Any, lon: Any) -> tuple[float, float]:
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
    st.session_state["map_revision"] += 1
    return "added"


def remove_active_point() -> None:
    """Delete the point currently on screen, keeping it restorable.

    "Clear All Points" was the only way to correct a single misplaced click, which meant
    one slip discarded up to ninety-nine analysed sites.
    """
    points = st.session_state["target_points"]
    index = active_point_index()
    if not 0 <= index < len(points):
        return
    # Bounded history: enough to recover from a slip, not a second copy of the dataset.
    st.session_state["removed_points"] = (st.session_state.get("removed_points") or [])[-9:]
    st.session_state["removed_points"].append((index, points.pop(index)))
    st.session_state["selected_point"] = min(index, len(points) - 1) if points else None
    # Cached analyses stay keyed by coordinate, so restoring a point costs no new quota.
    st.session_state["last_click"] = None
    st.session_state["map_revision"] += 1


def undo_remove() -> None:
    """Put the most recently removed point back where it was."""
    stack = st.session_state.get("removed_points") or []
    if not stack:
        return
    index, point = stack.pop()
    points = st.session_state["target_points"]
    points.insert(min(index, len(points)), point)
    st.session_state["selected_point"] = min(index, len(points) - 1)
    st.session_state["map_revision"] += 1


def manual_entry() -> None:
    """Type a coordinate directly.

    Clicking the map was the only way to place a point, which is unusable by keyboard
    (WCAG 2.1.1) and hopeless for operators who already hold surveyed coordinates.
    """
    section("manual_entry")
    with st.form("manual_point", clear_on_submit=False):
        lat_field, lon_field = st.columns(2)
        lat_value = lat_field.number_input(tr("lat"), -90.0, 90.0, 0.0, format="%.6f", step=1e-6)
        lon_value = lon_field.number_input(tr("lon"), -180.0, 180.0, 0.0, format="%.6f", step=1e-6)
        if st.form_submit_button(tr("add_point"), use_container_width=True, type="secondary"):
            outcome = add_point(lat_value, lon_value, "manual")
            if outcome == "added":
                st.session_state["selected_point"] = len(st.session_state["target_points"]) - 1
                st.session_state["map_view"] = {"lat": lat_value, "lon": lon_value,
                                                "bounds": None, "label": tr("manual_entry")}
                notice("success", "manual_added")
            else:
                notice("warning" if outcome in {"limit", "duplicate"} else "error", outcome)
            st.rerun()
    st.caption(tr("manual_hint"))


@st.cache_data(ttl=CACHE_TTL, max_entries=CACHE_MAX_ENTRIES, show_spinner=False)
def parse_upload(data: bytes, name: str) -> pd.DataFrame:
    buffer = io.BytesIO(data)
    if Path(name).suffix.lower() == ".xlsx":
        return pd.read_excel(buffer, engine="openpyxl", nrows=MAX_UPLOAD_ROWS)
    try:
        return pd.read_csv(buffer, sep=None, engine="python", nrows=MAX_UPLOAD_ROWS)
    except UnicodeDecodeError:
        buffer.seek(0)
        return pd.read_csv(buffer, sep=None, engine="python", encoding="latin-1", nrows=MAX_UPLOAD_ROWS)


def header_tokens(value: Any) -> list[str]:
    """Split a spreadsheet header into comparable words, ignoring units and punctuation."""
    return re.sub(r"[^a-z0-9]+", " ", str(value).strip().lower()).split()


def find_column(columns: Sequence[Any], names: set[str], taken: Any | None = None) -> Any | None:
    """Locate a coordinate column by exact header, then by any recognised word in it.

    Two passes rather than one so that an exact "lat" always beats a fuzzy hit elsewhere
    in the sheet, and `taken` stops a single header like "lat_lon" being claimed twice.
    """
    candidates = [column for column in columns if column is not taken]
    joined = {"".join(header_tokens(column)): column for column in candidates}
    for name in sorted(names, key=len, reverse=True):
        if name in joined:
            return joined[name]
    for column in candidates:
        if set(header_tokens(column)) & names:
            return column
    return None


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
    lat_col = find_column(frame.columns, LAT_NAMES)
    lon_col = find_column(frame.columns, LON_NAMES, taken=lat_col)
    if lat_col is None or lon_col is None:
        # Name what was actually seen: "no supported columns" alone left the operator
        # guessing which of their headers the app was willing to accept.
        seen = ", ".join(str(column) for column in list(frame.columns)[:12]) or "—"
        notice("error", "columns_error", name=safe_name)
        notice("info", "columns_seen", columns=seen)
        return
    added = skipped = 0
    # strict=True: the two columns come from one DataFrame and are the same length by
    # construction. If that ever stops being true, fail loudly instead of dropping rows.
    for lat, lon in zip(frame[lat_col], frame[lon_col], strict=True):
        if add_point(lat, lon, "upload") == "added": added += 1
        else: skipped += 1
    notice("success" if added else "warning", "upload_ok" if added else "empty_upload", **({"count": added, "name": safe_name} if added else {"name": safe_name}))
    if skipped: notice("warning", "skipped", count=skipped)


def osm_place_label(properties: Mapping[str, Any]) -> str:
    """Build a concise suggestion label from Photon/OpenStreetMap fields."""
    parts: list[str] = []
    street = " ".join(str(value).strip() for value in
                      (properties.get("street"), properties.get("housenumber")) if value)
    values = (properties.get("name"), street, properties.get("district"),
              properties.get("city") or properties.get("town") or properties.get("village"),
              properties.get("state"), properties.get("country"))
    for raw_value in values:
        value = str(raw_value).strip() if raw_value else ""
        if value and value.casefold() not in {part.casefold() for part in parts}:
            parts.append(value)
    return ", ".join(parts)


@st.cache_data(ttl=3600, max_entries=CACHE_MAX_ENTRIES, show_spinner=False)
def autocomplete_osm_location(query: str, language: str) -> list[tuple[str, dict[str, Any]]]:
    """Return broad POI/address suggestions from Photon while the user types."""
    normalized = " ".join(query.split())
    if len(normalized) < 3:
        return []
    try:
        response = requests.get(
            "https://photon.komoot.io/api",
            params={"q": normalized, "limit": "12", "lang": "en"},
            headers={"User-Agent": "OmniSite-Telco-Intelligence/1.0 (OSM location autocomplete)"},
            timeout=8,
        )
        response.raise_for_status()
        suggestions: list[tuple[str, dict[str, Any]]] = []
        seen: set[tuple[float, float]] = set()
        for feature in response.json().get("features", []):
            coordinates = feature.get("geometry", {}).get("coordinates", [])
            properties = feature.get("properties", {})
            if len(coordinates) < 2 or not valid_coordinate(coordinates[1], coordinates[0]):
                continue
            lat, lon = float(coordinates[1]), float(coordinates[0])
            coordinate = coord_key(lat, lon)
            label = osm_place_label(properties)
            if not label or coordinate in seen:
                continue
            seen.add(coordinate)
            suggestion = {"lat": lat, "lon": lon, "bounds": None, "label": label,
                          "osm_type": properties.get("osm_type"), "osm_id": properties.get("osm_id")}
            suggestions.append((label, suggestion))
        return suggestions
    except (requests.RequestException, TypeError, ValueError) as exc:
        LOGGER.info("OSM autocomplete unavailable: %s", exc)
        return []


def location_suggestions(query: str) -> list[tuple[str, dict[str, Any]]]:
    """Bind the current interface language to the autocomplete callback."""
    return autocomplete_osm_location(query, st.session_state.get("language", "EN"))


def focus_location(location: Mapping[str, Any]) -> None:
    """Focus the map immediately after an autocomplete suggestion is selected."""
    st.session_state["map_view"] = dict(location)
    st.session_state["map_revision"] += 1
    notice("success", "search_found", location=location["label"])


@st.cache_resource(show_spinner=False)
def initialize_gee() -> tuple[bool, str | None]:
    """Initialize Earth Engine once per process without session-thread coupling."""
    try:
        if GEE_KEY.is_file():
            with GEE_KEY.open(encoding="utf-8") as file:
                credentials_data = json.load(file)
            email, project = credentials_data.get("client_email"), credentials_data.get("project_id")
            if not email: raise ValueError("client_email missing from service-account JSON")
            credentials = ee.ServiceAccountCredentials(email, str(GEE_KEY))
            try:
                ee.Initialize(credentials, project=project)
            except Exception as project_exc:
                # project_id in the service-account file is not necessarily the project
                # registered with Earth Engine. Forcing it makes init fail and drops the
                # whole pipeline to hardcoded fallbacks, so let EE resolve it instead.
                LOGGER.info("Earth Engine rejected project %s; resolving from service account: %s", project, project_exc)
                ee.Initialize(credentials)
        else:
            ee.Initialize()
        return True, None
    except Exception as exc:
        LOGGER.info("Earth Engine unavailable; hybrid engine selected: %s", exc)
        return False, str(exc)


@st.cache_data(ttl=CACHE_TTL, max_entries=CACHE_MAX_ENTRIES, show_spinner=False)
def get_gee_data(lat: float, lon: float) -> dict[str, Any]:
    result: dict[str, Any] = {"available": False, "elevation": None, "slope": None, "land_cover": None,
              "population": None, "night_light": None, "water_occurrence": None, "error": None}
    try:
        point, area = ee.Geometry.Point([lon, lat]), ee.Geometry.Point([lon, lat]).buffer(500)
        dem = ee.Image("USGS/SRTMGL1_003").select("elevation")
        elevation = dem.reduceRegion(ee.Reducer.mean(), point, 30, bestEffort=True,
                                     maxPixels=1_000_000).get("elevation")
        slope = ee.Terrain.slope(dem).reduceRegion(
            ee.Reducer.mean(), area, 30, bestEffort=True,
            maxPixels=2_000_000).get("slope")
        cover = ee.Image("ESA/WorldCover/v100/2020").select("Map").reduceRegion(
            ee.Reducer.mode(), area, 10, bestEffort=True,
            maxPixels=5_000_000).get("Map")
        # Track the newest WorldPop vintage available rather than pinning a fixed
        # year, so the estimate does not silently go stale as the catalogue grows.
        pop_collection = ee.ImageCollection("WorldPop/GP/100m/pop").filterBounds(point).select("population")
        pop_image = pop_collection.filter(
            ee.Filter.eq("year", pop_collection.aggregate_max("year"))).mosaic()
        population = pop_image.reduceRegion(
            ee.Reducer.sum(), area, 100, bestEffort=True,
            maxPixels=2_000_000).get("population")
        night_image = (ee.ImageCollection("NOAA/VIIRS/DNB/MONTHLY_V1/VCMSLCFG")
                       .filterBounds(point).filterDate("2023-01-01", "2025-01-01").select("avg_rad").median())
        night_light = night_image.reduceRegion(
            ee.Reducer.mean(), area, 500, bestEffort=True,
            maxPixels=1_000_000).get("avg_rad")
        water_image = ee.Image("JRC/GSW1_4/GlobalSurfaceWater").select("occurrence")
        water_occurrence = water_image.reduceRegion(
            ee.Reducer.max(), area, 30, bestEffort=True,
            maxPixels=2_000_000).get("occurrence")
        values = ee.Dictionary({
            "elevation": elevation,
            "slope": slope,
            "cover": cover,
            "population": population,
            "night_light": night_light,
            "water_occurrence": water_occurrence,
        }).getInfo()
        # getInfo returns None when Earth Engine answers with an empty result. Reading
        # .get off that raised AttributeError, which the broad handler below reported as
        # an opaque engine error rather than "this point has no data".
        if not values:
            result["error"] = "Earth Engine returned no values for this point"
            return result
        elevation = values.get("elevation")
        slope = values.get("slope")
        cover = values.get("cover")
        population = values.get("population")
        night_light = values.get("night_light")
        water_occurrence = values.get("water_occurrence")
        result.update({"available": any(v is not None for v in (elevation, cover, population)),
            "elevation": float(elevation) if elevation is not None else None, "slope": float(slope) if slope is not None else None,
            # mode() returns a float carrying rounding error (49.999999999999964 for a
            # pixel whose class is 50). int() truncates and silently shifts the class,
            # so round to the nearest ESA WorldCover class instead.
            "land_cover": round(cover) if cover is not None else None, "population": float(population) if population is not None else None,
            "night_light": float(night_light) if night_light is not None else None,
            "water_occurrence": float(water_occurrence) if water_occurrence is not None else None})
    except Exception as exc: result["error"] = str(exc)
    return result


@st.cache_data(ttl=CACHE_TTL, max_entries=CACHE_MAX_ENTRIES, show_spinner=False)
def get_geospatial_fallback(lat: float, lon: float) -> dict[str, Any]:
    """Return a resilient public-elevation and density estimate when GEE is blocked."""
    elevation: float | None = None
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
    # Only elevation has a real public source here. Everything else used to be a
    # bounding-box constant (12 900 people, 1.4 deg, "Cropland") that looked like a
    # measurement and was identical for every point — including open sea. Report
    # nothing rather than fabricate.
    return {
        "available": elevation is not None,
        "fallback": True,
        "elevation": elevation,
        "slope": None,
        "land_cover": None,
        "population": None,
        "night_light": None,
        "water_occurrence": None,
        "error": None,
    }


# Overpass rejects the default python-requests agent with HTTP 406, and the primary
# endpoint frequently returns 504 under load, so identify ourselves and fail over.
OVERPASS_AGENT = "OmniSite/1.0 (telco site screening)"
# kumi.systems and private.coffee both read-timed-out on every probe, so they only
# added dead wait before the fallback; keep the two that actually answer.
OVERPASS_ENDPOINTS = (
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
    "https://overpass-api.de/api/interpreter",
)


def overpass_query(query: str, timeout: int = 12) -> dict[str, Any] | None:
    """Run an Overpass query against the first endpoint that answers with JSON."""
    for endpoint in OVERPASS_ENDPOINTS:
        try:
            response = requests.post(endpoint, data={"data": query},
                                     headers={"User-Agent": OVERPASS_AGENT}, timeout=timeout)
            response.raise_for_status()
            return response.json()
        except Exception as exc:
            LOGGER.info("Overpass endpoint %s unavailable: %s", endpoint, exc)
    return None


@st.cache_data(ttl=CACHE_TTL, max_entries=CACHE_MAX_ENTRIES, show_spinner=False)
def get_context_features(lat: float, lon: float) -> dict[str, Any]:
    """Query power, strategic POI, and water context in one resilient Overpass request."""
    result: dict[str, Any] = {
        "available": False, "power_count": 0, "power_distance": None,
        "poi_count": 0, "poi_types": {"school": 0, "university": 0, "hospital": 0, "marketplace": 0},
        "water_distance": None, "error": None,
    }
    query = f"""[out:json][timeout:20];(
      nwr[power~"line|minor_line|tower|pole|substation|generator"](around:2000,{lat},{lon});
      nwr[amenity~"school|university|hospital|marketplace"](around:1000,{lat},{lon});
      nwr[natural=water](around:1500,{lat},{lon});
      nwr[waterway~"river|stream|canal|drain"](around:1500,{lat},{lon});
    );out center tags;"""
    payload = overpass_query(query)
    if payload is None:
        result["error"] = "All Overpass endpoints unavailable"
        return result
    try:
        for element in payload.get("elements", []):
            tags = element.get("tags", {})
            y = element.get("lat", element.get("center", {}).get("lat"))
            x = element.get("lon", element.get("center", {}).get("lon"))
            distance = haversine(lat, lon, float(y), float(x)) if valid_coordinate(y, x) else None
            if tags.get("power"):
                result["power_count"] += 1
                if distance is not None:
                    result["power_distance"] = min(result["power_distance"] or distance, distance)
            amenity = tags.get("amenity")
            if amenity in result["poi_types"]:
                result["poi_types"][amenity] += 1
                result["poi_count"] += 1
            if distance is not None and (tags.get("natural") == "water" or tags.get("waterway")):
                result["water_distance"] = min(result["water_distance"] or distance, distance)
        result["available"] = True
    except Exception as exc:
        LOGGER.info("OSM context query unavailable: %s", exc)
        result["error"] = str(exc)
    return result


@st.cache_data(ttl=CACHE_TTL, max_entries=CACHE_MAX_ENTRIES, show_spinner=False)
def get_wind_hazard(lat: float, lon: float) -> dict[str, Any]:
    """Return maximum daily gust from the latest complete ten-year archive window."""
    result: dict[str, Any] = {"available": False, "max_gust": None, "tower_class": None, "error": None}
    try:
        end = datetime.now(timezone.utc).date() - timedelta(days=7)
        start = end - timedelta(days=3652)
        response = requests.get(
            "https://archive-api.open-meteo.com/v1/archive",
            params={"latitude": str(lat), "longitude": str(lon), "start_date": start.isoformat(),
                    "end_date": end.isoformat(), "daily": "wind_gusts_10m_max",
                    "wind_speed_unit": "kmh", "timezone": "UTC"},
            # A cold ten-year daily archive request takes ~15s; the old 12s ceiling
            # turned healthy responses into "Unavailable".
            timeout=45,
        )
        response.raise_for_status()
        values = [float(value) for value in response.json().get("daily", {}).get("wind_gusts_10m_max", [])
                  if value is not None and math.isfinite(float(value))]
        if values:
            maximum = max(values)
            tower_class = "heavy" if maximum >= 100 else "reinforced" if maximum >= 75 else "standard"
            result.update({"available": True, "max_gust": maximum, "tower_class": tower_class})
    except Exception as exc:
        LOGGER.info("Wind archive unavailable: %s", exc)
        result["error"] = str(exc)
    return result


# A verdict needs a majority of the seven screening signals to mean anything. Below this
# the site is reported as unscreened rather than scored, because the alternative — the
# old behaviour — was to treat every unmeasured signal as benign and return 82/100
# APPROVE for a point where every single engine had failed.
SCORE_SIGNALS = ("land_cover", "power", "flood", "wind", "market", "access", "terrain")
MIN_SIGNALS_FOR_VERDICT = 4


def derive_site_intelligence(gee_data: Mapping[str, Any], context: Mapping[str, Any],
                             wind: Mapping[str, Any], road: Mapping[str, Any] | None = None,
                             rf: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Convert raw geospatial indicators into transparent telco business decisions.

    Every penalty is anchored to a signal that was actually measured. A signal no engine
    could return is recorded as unknown and carries no penalty *and* no verdict — the
    data layer already refuses to invent numbers, and scoring must not undo that by
    reading silence as good news.
    """
    road, rf = road or {}, rf or {}
    measured: dict[str, bool] = {}

    cover = gee_data.get("land_cover")
    measured["land_cover"] = cover is not None
    permit = ("unknown" if cover is None else "restricted" if cover in {80, 90, 95}
              else "high" if cover == 10 else "medium" if cover == 40 else "low")
    permit_note = ("permit_unscreened" if permit == "unknown" else "permit_water" if permit == "restricted"
                   else "permit_forest" if permit == "high" else "permit_agri" if permit == "medium"
                   else "permit_built")

    light, power_distance = gee_data.get("night_light"), context.get("power_distance")
    measured["power"] = light is not None or bool(context.get("available"))
    if light is not None:
        off_grid = light < 0.5 and (power_distance is None or power_distance > 1500)
    elif context.get("available"):
        off_grid = context.get("power_count", 0) == 0 and cover != 50
    else:
        off_grid = False

    water_distance, occurrence = context.get("water_distance"), gee_data.get("water_occurrence")
    measured["flood"] = occurrence is not None or bool(context.get("available"))
    if not measured["flood"]:
        flood = "unknown"
    elif (occurrence is not None and occurrence >= 50) or (water_distance is not None and water_distance < 100):
        flood = "high"
    elif (occurrence is not None and occurrence >= 10) or (water_distance is not None and water_distance < 300):
        flood = "medium"
    else:
        flood = "low"

    measured["market"] = bool(context.get("available"))
    poi_count = int(context.get("poi_count", 0))
    market = ("unknown" if not measured["market"] else "high" if poi_count >= 8
              else "medium" if poi_count >= 3 else "low")

    tower_class = wind.get("tower_class")
    measured["wind"] = tower_class is not None

    # Every mast needs a build and maintenance route. Cutting a new one is the largest
    # single civil-works line item, so "no drivable road within 500 m" is a hard finding.
    measured["access"] = bool(road.get("available"))
    road_distance = 500.0 if road.get("no_road") else road.get("distance")
    access = ("unknown" if not measured["access"] else "none" if road.get("no_road")
              else "far" if (road_distance or 0) > 250 else "near")

    # Steep ground multiplies foundation, retaining-wall and haulage cost.
    slope = gee_data.get("slope")
    measured["terrain"] = slope is not None
    terrain = ("unknown" if slope is None else "steep" if slope >= 25
               else "moderate" if slope >= 10 else "flat")

    # Collocation skips the tower build entirely — a real cost advantage, not a penalty.
    collocation = rf.get("status") == "collocation"

    score = 82
    score -= {"low": 0, "medium": 12, "high": 25, "restricted": 45, "unknown": 0}[permit]
    score -= 18 if off_grid else 0
    score -= {"low": 0, "medium": 12, "high": 30, "unknown": 0}[flood]
    score -= {"heavy": 15, "reinforced": 6}.get(tower_class or "", 0)
    score -= {"none": 22, "far": 8, "near": 0, "unknown": 0}[access]
    score -= {"steep": 20, "moderate": 8, "flat": 0, "unknown": 0}[terrain]
    score += {"high": 10, "medium": 5}.get(market, 0)
    score += 8 if collocation else 0
    score = max(0, min(100, score))

    known = sum(measured.values())
    if known < MIN_SIGNALS_FOR_VERDICT:
        recommendation = "insufficient"
    elif score < 45 or permit == "restricted" or flood == "high" or access == "none":
        recommendation = "avoid"
    # A thin but passing screening is a review, never an approval: three unknown signals
    # can hide exactly the constraint that would have failed the site. Steep ground and a
    # distant access road are likewise survey questions, not desk-approvable.
    elif score < 70 or known < len(SCORE_SIGNALS) or terrain == "steep" or access == "far":
        recommendation = "review"
    else:
        recommendation = "approve"

    return {"permit": permit, "permit_note": permit_note, "off_grid": off_grid, "flood": flood,
            "market": market, "access": access, "terrain": terrain, "collocation": collocation,
            "score": None if recommendation == "insufficient" else score,
            "known_signals": known, "total_signals": len(measured),
            "recommendation": recommendation}


def tag(value: Any) -> str:
    if isinstance(value, (list, tuple, set)): return ", ".join(map(str, value))
    return str(value) if value not in (None, "") else "unknown"


@st.cache_data(ttl=CACHE_TTL, max_entries=CACHE_MAX_ENTRIES, show_spinner=False)
def get_nearest_road(lat: float, lon: float) -> dict[str, Any]:
    result: dict[str, Any] = {"available": False, "distance": None, "road_type": None, "highway": None,
              "no_road": False, "error": None}
    try:
        ox.settings.requests_timeout = 30
        # overpass-api.de blocks the default agent (406) and 504s under load, which
        # left OSM Roads permanently DEGRADED. Identify ourselves and use the mirror
        # that actually answers.
        ox.settings.default_user_agent = OVERPASS_AGENT
        ox.settings.overpass_endpoint = "https://maps.mail.ru/osm/tools/overpass/api"
        # This mirror does not publish slot availability, so osmnx's rate limiter waits
        # on a status it never gets and stalls minutes per point. Responses are cached
        # to ./cache, so repeat lookups stay cheap without it.
        ox.settings.overpass_rate_limit = False
        graph = ox.graph_from_point((lat, lon), dist=500, network_type="drive", simplify=True)
        # nearest_edges reports distance in the graph's CRS units. graph_from_point
        # returns EPSG:4326, so querying it directly yields degrees, which round to
        # 0 when rendered as metres. Project to UTM and query there instead.
        projected = ox.project_graph(graph)
        point, _ = ox.projection.project_geometry(Point(lon, lat), to_crs=projected.graph["crs"])
        edge, distance = ox.distance.nearest_edges(projected, X=point.x, Y=point.y, return_dist=True)
        # Projection preserves node ids, so edge attributes still resolve on the original graph.
        attrs = graph.get_edge_data(edge[0], edge[1], edge[2]) or {}
        highway, name = tag(attrs.get("highway")), tag(attrs.get("name"))
        result.update({"available": True, "distance": float(distance), "road_type": name if name != "unknown" else highway, "highway": highway})
    except Exception as exc:
        # Offshore and remote points legitimately have no drive network within 500 m.
        # OSMnx raises for that case, which is an answer ("no road"), not a failure.
        message = str(exc)
        if "No data elements" in message or "Found no graph nodes" in message:
            result.update({"available": True, "no_road": True})
        elif isinstance(exc, UnboundLocalError) and "response" in message:
            # osmnx 1.7 leaks this when its Overpass call fails; it means "no answer",
            # not "no road", so surface it as a real error rather than a false negative.
            result["error"] = "Overpass unavailable for road network"
        else:
            result["error"] = message
    return result


def haversine(a: float, b: float, c: float, d: float) -> float:
    p1, p2, dp, dl = math.radians(a), math.radians(c), math.radians(c-a), math.radians(d-b)
    value = math.sin(dp/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    value = min(1.0, max(0.0, value))
    return 12_742_000 * math.atan2(math.sqrt(value), math.sqrt(1-value))


@st.cache_data(ttl=CACHE_TTL, max_entries=CACHE_MAX_ENTRIES, show_spinner=False)
def opencellid_nearest(lat: float, lon: float) -> tuple[dict[str, Any] | None, bool]:
    if not OPENCELLID_KEY:
        return None, False
    return _opencellid_in_box(lat, lon, OPENCELLID_MAX_SPAN_DEG)


def _opencellid_in_box(lat: float, lon: float, span: float) -> tuple[dict[str, Any] | None, bool]:
    """Nearest cell in the box, and whether the lookup itself succeeded.

    The second element is what separates "no tower here" from "could not check" —
    collapsing the two produced confident greenfield verdicts on quota errors.
    """
    cells = _opencellid_raw(lat, lon, span)
    if cells is None:
        return None, False
    candidates = []
    for cell in cells:
        if valid_coordinate(cell.get("lat"), cell.get("lon")):
            distance = haversine(lat, lon, float(cell["lat"]), float(cell["lon"]))
            candidates.append((distance, cell))
    if not candidates:
        return None, True
    distance, cell = min(candidates, key=lambda item: item[0])
    return {"distance": distance, "id": f"OCID-{cell.get('cellid', cell.get('cell', 'UNKNOWN'))}",
            "lat": float(cell["lat"]), "lon": float(cell["lon"])}, True


@st.cache_data(ttl=CACHE_TTL, max_entries=CACHE_MAX_ENTRIES, show_spinner=False)
def check_collocation(lat: float, lon: float) -> dict[str, Any]:
    empty = {"available": False, "distance": None, "tower_id": None, "status": None,
             "tower_lat": None, "tower_lon": None, "no_tower": False, "error": None}
    if not OPENCELLID_KEY:
        return {**empty, "error": "OpenCelliD API key not configured"}
    try:
        live, looked_up = opencellid_nearest(lat, lon)
        if not looked_up:
            # Quota exhausted, network failure, bad key — an unknown, not a greenfield.
            return {**empty, "error": "OpenCelliD lookup unavailable"}
        if live is None:
            # OpenCelliD holds no cell anywhere near this point. That is a real finding —
            # the strongest possible greenfield signal — not a reason to invent a tower.
            return {**empty, "available": True, "no_tower": True, "status": "greenfield"}
        return {"available": True, "distance": live["distance"], "tower_id": live["id"],
                "status": "greenfield" if live["distance"] > COLLOCATION_RADIUS_M else "collocation",
                "tower_lat": live["lat"], "tower_lon": live["lon"], "no_tower": False, "error": None}
    except Exception as exc:
        return {**empty, "error": str(exc)}


def run_analysis(lat: float, lon: float) -> dict[str, dict[str, Any]]:
    """Run independent intelligence engines concurrently for low latency."""
    def geospatial_engine() -> dict[str, Any]:
        ready, error = initialize_gee()
        gee_result = get_gee_data(lat, lon) if ready else get_geospatial_fallback(lat, lon)
        if not ready:
            gee_result["initialization_error"] = error
        elif not gee_result.get("available"):
            gee_result = {
                **get_geospatial_fallback(lat, lon),
                "initialization_error": gee_result.get("error"),
            }
        return gee_result

    # Mixed arities on purpose: geospatial_engine closes over lat/lon, the rest take them.
    engines: dict[str, Any] = {
        "road": get_nearest_road,
        "rf": check_collocation,
        "context": get_context_features,
        "wind": get_wind_hazard,
        "gee": geospatial_engine,
    }
    results: dict[str, Any] = {}
    with ThreadPoolExecutor(max_workers=len(engines),
                            thread_name_prefix="omnisite-engine") as pool:
        futures: dict[Future[Any], str] = {
            pool.submit(function, lat, lon) if name != "gee" else pool.submit(function): name
            for name, function in engines.items()
        }
        for future in as_completed(futures):
            name = futures[future]
            try:
                results[name] = future.result()
            except Exception as exc:
                LOGGER.info("%s engine degraded safely: %s", name, exc)
                results[name] = {"available": False, "error": str(exc)}
    road, rf = results["road"], results["rf"]
    context, wind, gee_data = results["context"], results["wind"], results["gee"]
    decision = derive_site_intelligence(gee_data, context, wind, road, rf)
    return {"road": road, "rf": rf, "gee": gee_data, "context": context,
            "wind": wind, "decision": decision}


@st.cache_resource(show_spinner=False)
def analysis_executor() -> ThreadPoolExecutor:
    """Return a process-lifetime worker pool for non-blocking site analysis."""
    return ThreadPoolExecutor(max_workers=2, thread_name_prefix="omnisite-analysis")


def analysis_key(lat: float, lon: float) -> str:
    """Build the stable identity used by analysis jobs and results."""
    return f"{lat:.6f}:{lon:.6f}"


def queue_analysis(lat: float, lon: float) -> bool:
    """Submit exactly one background analysis for a coordinate, within budget.

    Returns False when the submission was refused. Both ceilings protect shared,
    metered resources: the worker pool is process-wide across every visitor, and each
    analysis spends OpenCelliD, Earth Engine and Overpass quota that nobody gets back.
    """
    key = analysis_key(lat, lon)
    if key in st.session_state["analysis_results"] or key in st.session_state["analysis_jobs"]:
        return True
    if key in st.session_state["analysis_failures"]:
        return False
    if len(st.session_state["analysis_jobs"]) >= MAX_QUEUED_JOBS:
        return False
    if rate_limited("analysis", RATE_LIMIT_ANALYSIS):
        return False
    st.session_state["analysis_jobs"][key] = analysis_executor().submit(run_analysis, lat, lon)
    st.session_state["analysis_started"][key] = time.monotonic()
    return True


def _collect(key: str) -> bool:
    """Move one finished future into results or failures. True when it was finished.

    Harvesting is separate from viewing on purpose: jobs are queued for every target
    point, so results have to be reaped for every point too. Reaping only the point on
    screen is what left the scorecard stuck on "Queued…" for work that had already
    completed, and starved segmentation of the five sites it needs.
    """
    future: Future[Any] | None = st.session_state["analysis_jobs"].get(key)
    if future is None:
        return False
    if not future.done():
        # A wedged engine used to leave the point on "Queued…" forever. The future cannot
        # be interrupted, so cancel what has not started and stop waiting on the rest.
        started = st.session_state["analysis_started"].get(key, time.monotonic())
        if time.monotonic() - started < JOB_TIMEOUT_SECONDS:
            return False
        future.cancel()
        st.session_state["analysis_jobs"].pop(key, None)
        st.session_state["analysis_started"].pop(key, None)
        st.session_state["analysis_failures"][key] = "timeout"
        LOGGER.warning("Analysis for %s exceeded %ss; abandoned", key, JOB_TIMEOUT_SECONDS)
        return True
    st.session_state["analysis_jobs"].pop(key, None)
    st.session_state["analysis_started"].pop(key, None)
    try:
        st.session_state["analysis_results"][key] = future.result()
    except Exception as exc:
        LOGGER.warning("Background analysis failed for %s: %s", key, exc)
        st.session_state["analysis_failures"][key] = str(exc)
    return True


def harvest_analyses() -> int:
    """Reap every finished background job. Returns how many are still in flight."""
    for key in list(st.session_state["analysis_jobs"]):
        _collect(key)
    return len(st.session_state["analysis_jobs"])


def current_analysis(lat: float, lon: float) -> tuple[dict[str, Any] | None, bool]:
    """Collect a completed future or report that the latest job is pending."""
    key = analysis_key(lat, lon)
    if key in st.session_state["analysis_results"]:
        return st.session_state["analysis_results"][key], False
    if key in st.session_state["analysis_failures"]:
        return None, False
    queue_analysis(lat, lon)
    if not _collect(key):
        return None, True
    return st.session_state["analysis_results"].get(key), False


def active_point_index() -> int:
    """Index of the point whose analysis is on screen, clamped to the current list."""
    points = st.session_state["target_points"]
    if not points:
        return -1
    index = st.session_state.get("selected_point")
    if index is None or not 0 <= index < len(points):
        return len(points) - 1
    return index


# Every feature below is a measured quantity from one of the five engines. Nothing here
# is synthesised, so the clustering describes real ground conditions rather than noise.
ML_FEATURES: tuple[tuple[str, str], ...] = (
    ("elevation", "feat_elevation"),
    ("slope", "feat_slope"),
    ("population", "feat_population"),
    ("night_light", "feat_nightlight"),
    ("water_occurrence", "feat_water"),
    ("poi_count", "feat_poi"),
    ("power_distance", "feat_power"),
    ("road_distance", "feat_road"),
    ("max_gust", "feat_gust"),
    ("tower_distance", "feat_tower"),
)
# Below this many analysed points a clustering says more about the algorithm than the sites.
MIN_SITES_FOR_SEGMENTATION = 5


def candidate_grid(lat: float, lon: float, radius_km: float, spacing_km: float) -> list[tuple[float, float]]:
    """Regular lat/lon grid over a square search area, clipped to a circle."""
    step_lat = spacing_km / 111.32
    step_lon = spacing_km / (111.32 * max(.2, math.cos(math.radians(lat))))
    steps = max(1, int(radius_km / spacing_km))
    points = []
    for i in range(-steps, steps + 1):
        for j in range(-steps, steps + 1):
            if math.hypot(i * spacing_km, j * spacing_km) > radius_km:
                continue
            points.append((round(lat + i * step_lat, 6), round(lon + j * step_lon, 6)))
    return points


# reduceRegions evaluates the whole batch server-side, but Earth Engine rejects a request
# long before ten thousand buffered features — the old uncapped grid built 7,845 of them
# for a 25 km / 0.5 km search and simply failed. Batch the sweep, and refuse a grid so
# fine that even batching would take an unreasonable number of round trips.
MAX_GRID_CELLS = 1500
DEMAND_BATCH = 150


def sample_demand(points: Sequence[tuple[float, float]], buffer_m: int = 500) -> list[dict[str, Any]]:
    """Population, land cover and slope for every candidate, in server-side batches.

    Sampling points one at a time would be hundreds of round trips for a single search;
    sending them all at once exceeds what Earth Engine will evaluate in one request.
    """
    population = ee.ImageCollection("WorldPop/GP/100m/pop").select("population")
    population = population.filter(ee.Filter.eq("year", population.aggregate_max("year"))).mosaic()
    cover = ee.Image("ESA/WorldCover/v100/2020").select("Map")
    slope = ee.Terrain.slope(ee.Image("USGS/SRTMGL1_003").select("elevation"))
    stacked = population.rename("pop").addBands(cover.rename("cover")).addBands(slope.rename("slope"))
    reducer = ee.Reducer.sum().setOutputs(["pop"]).combine(
        ee.Reducer.mode().setOutputs(["cover"]), sharedInputs=False).combine(
        ee.Reducer.mean().setOutputs(["slope"]), sharedInputs=False)

    rows: list[dict[str, Any]] = []
    for start in range(0, len(points), DEMAND_BATCH):
        chunk = points[start:start + DEMAND_BATCH]
        collection = ee.FeatureCollection([
            ee.Feature(ee.Geometry.Point([lon, lat]).buffer(buffer_m), {"idx": start + offset})
            for offset, (lat, lon) in enumerate(chunk)
        ])
        reduced = stacked.reduceRegions(collection=collection, reducer=reducer, scale=100)
        for feature in reduced.getInfo().get("features", []):
            properties = feature.get("properties", {})
            index = int(properties.get("idx", 0))
            rows.append({
                "lat": points[index][0], "lon": points[index][1],
                "population": properties.get("pop"),
                "land_cover": round(properties["cover"]) if properties.get("cover") is not None else None,
                "slope": properties.get("slope"),
            })
    return rows


# getInArea caps a query at 4 km², so a multi-kilometre sweep has to be tiled. The free
# OpenCelliD tier is a few thousand lookups a day, and the old 25 km / 0.5 km setting
# issued 729 of them one after another on a single button press — most of a day's budget,
# spent serially, with the whole app blocked behind it. Cap the sweep and fan it out.
MAX_TOWER_TILES = 121
TOWER_FETCH_WORKERS = 6


def tower_tile_centres(lat: float, lon: float, radius_km: float) -> list[tuple[float, float]]:
    """Centres of the OpenCelliD tiles needed to cover the search area."""
    span = OPENCELLID_MAX_SPAN_DEG
    step_lat = span * 2
    step_lon = span * 2 / max(.2, math.cos(math.radians(lat)))
    tiles_lat = max(1, int((radius_km / 111.32) / step_lat) + 1)
    tiles_lon = max(1, int((radius_km / (111.32 * max(.2, math.cos(math.radians(lat))))) / step_lon) + 1)
    return [(lat + i * step_lat, lon + j * step_lon)
            for i in range(-tiles_lat, tiles_lat + 1)
            for j in range(-tiles_lon, tiles_lon + 1)]


def collect_towers(lat: float, lon: float, radius_km: float) -> tuple[list[tuple[float, float]], str]:
    """Every OpenCelliD cell in the search area, plus a status for the sweep itself.

    The status is what separates "no towers here" from "we could not check" — collapsing
    the two makes covered ground look like a coverage gap, which is the one error this
    feature must never make.
    """
    if not OPENCELLID_KEY:
        return [], "no_key"
    centres = tower_tile_centres(lat, lon, radius_km)
    if len(centres) > MAX_TOWER_TILES:
        return [], "too_wide"
    span = OPENCELLID_MAX_SPAN_DEG
    seen: set[tuple[float, float]] = set()
    failed = 0
    with ThreadPoolExecutor(max_workers=TOWER_FETCH_WORKERS,
                            thread_name_prefix="omnisite-ocid") as pool:
        payloads = pool.map(lambda centre: _opencellid_raw(centre[0], centre[1], span), centres)
        for payload in payloads:
            if payload is None:
                failed += 1
                continue
            for cell in payload:
                if valid_coordinate(cell.get("lat"), cell.get("lon")):
                    seen.add((round(float(cell["lat"]), 5), round(float(cell["lon"]), 5)))
    if failed:
        LOGGER.warning("Tower sweep incomplete: %d of %d tiles failed", failed, len(centres))
    return sorted(seen), "ok" if failed == 0 else "partial"


@st.cache_data(ttl=CACHE_TTL, max_entries=CACHE_MAX_ENTRIES, show_spinner=False)
def _opencellid_raw(lat: float, lon: float, span: float) -> list[dict[str, Any]] | None:
    """Cells in one tile, or None when the lookup itself failed.

    OpenCelliD reports quota and key errors as HTTP 200 with an `error` key, so
    raise_for_status sees nothing wrong. Returning [] on those would make
    "we could not check" indistinguishable from "no towers here" — the difference
    between an unknown and a confident, wrong greenfield verdict.
    """
    try:
        dy, dx = span, span / max(.2, math.cos(math.radians(lat)))
        response = requests.get("https://opencellid.org/cell/getInArea", params={"key": OPENCELLID_KEY,
            "BBOX": f"{lat-dy},{lon-dx},{lat+dy},{lon+dx}", "format": "json", "limit": "100"}, timeout=20)
        response.raise_for_status()
        payload = response.json()
        if isinstance(payload, dict) and payload.get("error"):
            LOGGER.info("OpenCelliD refused the lookup: %s", payload["error"])
            return None
        return payload.get("cells", []) if isinstance(payload, dict) else (payload or [])
    except Exception as exc:
        LOGGER.info("OpenCelliD tile unavailable: %s", exc)
        return None


# Typical usable service radius of an existing macro site. Population inside it is
# already covered, so a candidate there adds nothing however crowded it is.
SERVICE_RADIUS_M = 800
# At twice the service radius the demand counts as fully unmet; between the two it
# ramps. A linear ramp to 3 km was the first attempt and it failed: population spans
# four orders of magnitude while urban tower gaps rarely clear 1 km, so the distance
# term stayed near-constant and ranking collapsed into "most crowded cell wins".
COVERAGE_REACH_M = SERVICE_RADIUS_M * 2
# ESA WorldCover classes a mast cannot sit on: permanent water, mangroves, moss.
UNBUILDABLE_COVER = {80, 95, 100}


@st.cache_data(ttl=CACHE_TTL, max_entries=CACHE_MAX_ENTRIES, show_spinner=False)
def recommend_sites(lat: float, lon: float, radius_km: float, spacing_km: float,
                    count: int) -> dict[str, Any]:
    """Propose build sites where measured demand is furthest from measured supply.

    Demand is WorldPop population; supply is the OpenCelliD cell inventory. A
    candidate scores highly only when both hold: people live there, and the
    nearest existing tower is far. Nothing is invented — a candidate with no
    population data is dropped rather than guessed at.
    """
    result: dict[str, Any] = {"available": False, "candidates": [], "towers": 0,
                              "scanned": 0, "error": None}
    try:
        grid = candidate_grid(lat, lon, radius_km, spacing_km)
        if not grid:
            return result
        if len(grid) > MAX_GRID_CELLS:
            result["error"], result["scanned"] = "grid_too_large", len(grid)
            return result
        towers, sweep = collect_towers(lat, lon, radius_km)
        # Refuse rather than guess: without a complete tower inventory every candidate
        # looks maximally underserved, and the app would confidently propose city-centre
        # sites that already sit beside a mast.
        if sweep != "ok":
            result["error"] = {"no_key": "no_key", "too_wide": "too_wide"}.get(sweep, "tower_lookup_failed")
            return result
        # Demand comes from Earth Engine, which the analysis pipeline initialises lazily
        # in its own thread. Do it here too, otherwise an uninitialised EE raised from
        # sample_demand and got reported to the operator as an OpenCelliD quota problem.
        ready, gee_error = initialize_gee()
        if not ready:
            LOGGER.warning("Site recommendation needs Earth Engine: %s", gee_error)
            result["error"] = "gee_unavailable"
            return result
        try:
            demand = sample_demand(grid)
        except Exception as exc:
            LOGGER.exception("Earth Engine demand sampling failed: %s", exc)
            result["error"] = "demand_unavailable"
            return result
        result["scanned"], result["towers"] = len(grid), len(towers)

        scored = []
        for row in demand:
            population = row.get("population")
            if not population or population <= 0:
                continue
            if row.get("land_cover") in UNBUILDABLE_COVER:
                continue
            distance = min((haversine(row["lat"], row["lon"], t_lat, t_lon)
                            for t_lat, t_lon in towers), default=None)
            # No tower anywhere in the search area is the strongest possible gap.
            reach = COVERAGE_REACH_M if distance is None else distance
            # Zero inside an existing site's service radius, ramping to 1 at twice it.
            unmet = min(1.0, max(0.0, (reach - SERVICE_RADIUS_M) / SERVICE_RADIUS_M))
            scored.append({**row, "tower_distance": distance,
                           "unmet_people": row["population"] * unmet})
        scored = [row for row in scored if row["unmet_people"] > 0]
        if not scored:
            return result

        peak = max(row["unmet_people"] for row in scored) or 1.0
        for row in scored:
            # Rank by people not already covered, not by raw headcount — a crowded
            # cell beside an existing mast is worth nothing to build.
            row["score"] = round(100 * row["unmet_people"] / peak, 1)
        scored.sort(key=lambda row: row["score"], reverse=True)

        # Keep proposals at least one grid step apart so the list isn't one hotspot.
        chosen: list[dict[str, Any]] = []
        for row in scored:
            if all(haversine(row["lat"], row["lon"], pick["lat"], pick["lon"]) > spacing_km * 1000 * .9
                   for pick in chosen):
                chosen.append(row)
            if len(chosen) >= count:
                break
        result.update({"available": True, "candidates": chosen})
    except Exception as exc:
        LOGGER.exception("Site recommendation failed: %s", exc)
        result["error"] = str(exc)
    return result


def site_feature_vector(result: Mapping[str, Mapping[str, Any]]) -> dict[str, float | None]:
    """Flatten one analysis result into the measured features used for clustering."""
    gee, context = result.get("gee", {}), result.get("context", {})
    rf, wind, road = result.get("rf", {}), result.get("wind", {}), result.get("road", {})
    return {
        "elevation": gee.get("elevation"),
        "slope": gee.get("slope"),
        "population": gee.get("population"),
        "night_light": gee.get("night_light"),
        "water_occurrence": gee.get("water_occurrence"),
        "poi_count": context.get("poi_count") if context.get("available") else None,
        "power_distance": context.get("power_distance"),
        # "no road within 500 m" is a measurement, not a gap; encode it as the search ceiling.
        "road_distance": 500.0 if road.get("no_road") else road.get("distance"),
        "max_gust": wind.get("max_gust"),
        "tower_distance": rf.get("distance"),
    }


def segment_sites(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any] | None:
    """Unsupervised segmentation of analysed sites.

    KMeans groups sites by measured ground conditions and IsolationForest flags the
    profiles that sit apart from the rest. Both are unsupervised on purpose: there is
    no ground-truth label for "good telco site", and inventing one would make the
    output fiction. k is chosen by silhouette score rather than hardcoded.
    """
    import numpy as np
    from sklearn.cluster import KMeans
    from sklearn.ensemble import IsolationForest
    from sklearn.impute import SimpleImputer
    from sklearn.metrics import silhouette_score
    from sklearn.preprocessing import StandardScaler

    if len(rows) < MIN_SITES_FOR_SEGMENTATION:
        return None
    names = [key for key, _ in ML_FEATURES]
    raw = np.array([[row["features"].get(key) for key in names] for row in rows], dtype=float)
    # Drop features nobody measured for this batch; imputing an all-NaN column yields NaN.
    keep = [i for i in range(raw.shape[1]) if not np.isnan(raw[:, i]).all()]
    if len(keep) < 2:
        return None
    raw, names = raw[:, keep], [names[i] for i in keep]
    matrix = StandardScaler().fit_transform(SimpleImputer(strategy="median").fit_transform(raw))

    best: dict[str, Any] | None = None
    for k in range(2, min(5, len(rows) - 1) + 1):
        labels = KMeans(n_clusters=k, n_init=10, random_state=0).fit_predict(matrix)
        if len(set(labels)) < 2:
            continue
        quality = float(silhouette_score(matrix, labels))
        if best is None or quality > best["silhouette"]:
            best = {"labels": labels, "silhouette": quality, "k": k}
    if best is None:
        return None

    outliers = IsolationForest(random_state=0, contamination="auto").fit_predict(matrix) == -1
    # Describe each cluster by the standardised features furthest from the batch average,
    # so the label states what the data actually says instead of a marketing name.
    profiles = {}
    for cluster in sorted(set(best["labels"])):
        centre = matrix[best["labels"] == cluster].mean(axis=0)
        ranked = sorted(range(len(names)), key=lambda i: abs(centre[i]), reverse=True)[:2]
        traits = [tr("trait_high" if centre[i] > 0 else "trait_low", feature=tr(dict(ML_FEATURES)[names[i]]))
                  for i in ranked if abs(centre[i]) > .25]
        profiles[int(cluster)] = {
            "size": int((best["labels"] == cluster).sum()),
            "traits": traits or [tr("trait_average")],
        }
    return {"labels": [int(v) for v in best["labels"]], "outliers": [bool(v) for v in outliers],
            "silhouette": best["silhouette"], "k": best["k"], "profiles": profiles,
            "features_used": len(names)}


def analysed_sites(points: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Points whose analysis has completed, with their measured feature vectors."""
    ready = []
    for index, point in enumerate(points, 1):
        stored = st.session_state["analysis_results"].get(analysis_key(point["lat"], point["lon"]))
        if stored:
            ready.append({"index": index, "features": site_feature_vector(stored),
                          "decision": stored.get("decision") or {}})
    return ready


def export_button(frame: pd.DataFrame, stem: str, label_key: str) -> None:
    """Offer a rendered table as a CSV download.

    Screening output that cannot leave the browser is not usable evidence — each of these
    tables is something an operator has to hand to permitting, RF planning or finance.
    utf-8-sig so Excel opens the Chinese and Indonesian headers without mojibake.
    """
    if frame.empty:
        return
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    st.download_button(
        tr(label_key), frame.to_csv(index=False).encode("utf-8-sig"),
        file_name=f"omnisite-{stem}-{stamp}.csv", mime="text/csv", key=f"download_{stem}",
    )


def point_scorecard(points: Sequence[Mapping[str, Any]],
                    segments: Mapping[str, Any] | None = None,
                    ready: Sequence[Mapping[str, Any]] | None = None) -> pd.DataFrame:
    """One verdict row per target point, using only already-computed results."""
    labels = {"approve": tr("verdict_approve"), "review": tr("verdict_review"),
              "avoid": tr("verdict_avoid"), "insufficient": tr("verdict_insufficient")}
    cluster_of: dict[int, str] = {}
    if segments and ready:
        for position, site in enumerate(ready):
            mark = f'{tr("cluster")} {segments["labels"][position] + 1}'
            if segments["outliers"][position]:
                mark = f'{mark} · {tr("cluster_outlier")}'
            cluster_of[site["index"]] = mark
    rows = []
    for index, point in enumerate(points, 1):
        stored = st.session_state["analysis_results"].get(analysis_key(point["lat"], point["lon"]))
        decision = (stored or {}).get("decision") or {}
        failed = analysis_key(point["lat"], point["lon"]) in st.session_state["analysis_failures"]
        row = {
            tr("point"): index,
            tr("lat"): point["lat"],
            tr("lon"): point["lon"],
            tr("score"): decision.get("score"),
            tr("verdict"): labels.get(decision.get("recommendation") or "",
                                      tr("analysis_failed_short") if failed else tr("queued")),
        }
        if cluster_of:
            row[tr("cluster")] = cluster_of.get(index, "—")
        rows.append(row)
    return pd.DataFrame(rows)


def recommendation_panel(center: Mapping[str, Any] | None) -> None:
    """Search the surrounding area for build sites and show the ranked shortlist."""
    section("recommend", "recommend_desc")
    if center is None:
        st.info(tr("start"))
        return
    controls = st.columns([2, 2, 2, 3])
    # The radius ceiling is the tower-lookup budget, not an arbitrary limit: 8 km is
    # exactly MAX_TOWER_TILES lookups, and every kilometre past it costs quadratically.
    # The old 25 km ceiling issued 729 lookups on one press — most of a day's free quota.
    radius = controls[0].number_input(tr("recommend_radius"), 2.0, 8.0, 8.0, 1.0)
    spacing = controls[1].number_input(tr("recommend_spacing"), 0.5, 5.0, 2.0, .5)
    count = controls[2].number_input(tr("recommend_count"), 1, 10, 5, 1)
    cells = len(candidate_grid(center["lat"], center["lon"], float(radius), float(spacing)))
    tiles = len(tower_tile_centres(center["lat"], center["lon"], float(radius)))
    too_big = cells > MAX_GRID_CELLS or tiles > MAX_TOWER_TILES
    if controls[3].button(tr("recommend_run"), use_container_width=True, type="primary",
                          disabled=too_big):
        if rate_limited("recommend", RATE_LIMIT_RECOMMEND):
            st.warning(tr("rate_limited", limit=RATE_LIMIT_RECOMMEND))
        else:
            with st.spinner(tr("recommend_run")):
                st.session_state["recommendations"] = recommend_sites(
                    center["lat"], center["lon"], float(radius), float(spacing), int(count))
    # State the cost before it is spent, rather than after a minute of silence.
    st.caption(tr("recommend_estimate", cells=cells, tiles=tiles))
    if too_big:
        st.warning(tr("recommend_toobig", cells=cells, maximum=MAX_GRID_CELLS))
        return

    found = st.session_state.get("recommendations")
    if not found:
        return
    failure = found.get("error")
    if failure:
        st.warning(tr({
            "no_key": "recommend_nokey",
            "gee_unavailable": "recommend_nogee",
            "demand_unavailable": "recommend_nodemand",
            "grid_too_large": "recommend_toobig",
            "too_wide": "recommend_toowide",
        }.get(failure, "recommend_failed"),
            **({"cells": found.get("scanned", cells), "maximum": MAX_GRID_CELLS}
               if failure == "grid_too_large" else {})))
        return
    st.caption(tr("recommend_stats", scanned=found["scanned"], towers=found["towers"]))
    if not found["candidates"]:
        st.info(tr("recommend_none", radius=SERVICE_RADIUS_M))
        return
    rows = []
    for rank, candidate in enumerate(found["candidates"], 1):
        rows.append({
            tr("candidate"): rank,
            tr("lat"): candidate["lat"],
            tr("lon"): candidate["lon"],
            tr("score"): candidate["score"],
            tr("population"): round(candidate["population"]),
            tr("unmet"): round(candidate["unmet_people"]),
            tr("nearest_tower"): (tr("meters", value=f'{candidate["tower_distance"]:,.0f}')
                                  if candidate["tower_distance"] is not None else tr("no_tower")),
        })
    candidates = pd.DataFrame(rows)
    st.dataframe(
        candidates, use_container_width=True, hide_index=True,
        column_config={tr("lat"): st.column_config.NumberColumn(format="%.5f"),
                       tr("lon"): st.column_config.NumberColumn(format="%.5f"),
                       tr("score"): st.column_config.ProgressColumn(min_value=0, max_value=100, format="%d")},
    )
    export_button(candidates, "candidates", "export_candidates")


def segmentation_panel(ready: Sequence[Mapping[str, Any]]) -> dict[str, Any] | None:
    """Render the unsupervised segmentation, or say what is still needed to run it."""
    section("segmentation", "segmentation_desc")
    if len(ready) < MIN_SITES_FOR_SEGMENTATION:
        st.info(tr("segmentation_need", count=MIN_SITES_FOR_SEGMENTATION))
        return None
    try:
        segments = segment_sites(ready)
    except Exception as exc:
        LOGGER.exception("Segmentation failed: %s", exc)
        return None
    if not segments:
        return None
    found = tr("clusters_found", k=segments["k"], features=segments["features_used"])
    quality = tr("silhouette", value=f'{segments["silhouette"]:.2f}')
    st.caption(f"{found} · {quality}")
    columns = st.columns(len(segments["profiles"]))
    # strict=True: the column count is derived from the profile count on the line above,
    # so a mismatch means the segmentation result is malformed and should not render.
    for column, (cluster, profile) in zip(columns, sorted(segments["profiles"].items()), strict=True):
        with column:
            st.markdown(
                '<div class="rf-card">'
                f'<div class="rf-label">{html.escape(tr("cluster"))} {cluster + 1}</div>'
                f'<div class="rf-value">{html.escape(tr("cluster_size", count=profile["size"]))}</div>'
                f'<div class="rf-delta">↳ {html.escape(", ".join(profile["traits"]))}</div>'
                '</div>',
                unsafe_allow_html=True,
            )
    return segments


def _navigator_body() -> None:
    points = st.session_state["target_points"]
    index = active_point_index()
    outstanding = harvest_analyses()
    section("per_point", "per_point_desc")
    previous, picker, following, remove, undo = st.columns([1, 6, 1, 1, 1])
    if remove.button("🗑", use_container_width=True, help=tr("remove_point")):
        remove_active_point()
        st.rerun(scope="app")
    if undo.button("↩", use_container_width=True, help=tr("undo_remove"),
                   disabled=not st.session_state.get("removed_points")):
        undo_remove()
        st.rerun(scope="app")
    # Point selection changes the map marker and the intelligence panel too, so it has
    # to rerun the whole app rather than just this fragment.
    if previous.button("◀", use_container_width=True, help=tr("prev_point"), disabled=index == 0):
        st.session_state["selected_point"] = index - 1
        st.rerun(scope="app")
    if following.button("▶", use_container_width=True, help=tr("next_point"), disabled=index >= len(points) - 1):
        st.session_state["selected_point"] = index + 1
        st.rerun(scope="app")
    choice = picker.selectbox(
        tr("choose_point"),
        options=list(range(len(points))),
        index=index,
        format_func=lambda i: f"{tr('point')} {i + 1} — {points[i]['lat']:.5f}, {points[i]['lon']:.5f}",
        label_visibility="collapsed",
        key="point_picker",
    )
    if choice != index:
        st.session_state["selected_point"] = choice
        st.rerun(scope="app")
    ready = analysed_sites(points)
    if outstanding:
        st.caption(tr("batch_progress", done=len(ready), total=len(points)))
    segments = segmentation_panel(ready)
    scorecard = point_scorecard(points, segments, ready)
    st.dataframe(
        scorecard, use_container_width=True, hide_index=True,
        column_config={tr("lat"): st.column_config.NumberColumn(format="%.5f"),
                       tr("lon"): st.column_config.NumberColumn(format="%.5f"),
                       tr("score"): st.column_config.ProgressColumn(min_value=0, max_value=100, format="%d")},
    )
    export_button(scorecard, "scorecard", "export_scorecard")


@st.fragment(run_every=2.0)
def _navigator_polling() -> None:
    _navigator_body()


@st.fragment
def _navigator_idle() -> None:
    _navigator_body()


def point_navigator() -> None:
    """Let the operator step through every target point instead of only the newest.

    Poll while background jobs are still in flight so finished analyses appear in the
    scorecard on their own, then fall idle. Batch work is queued for every point, so
    without this the table only ever filled in for points the operator happened to open.
    """
    if len(st.session_state["target_points"]) < 2:
        return
    if st.session_state["analysis_jobs"]:
        _navigator_polling()
    else:
        _navigator_idle()


def job_pending(lat: float, lon: float) -> bool:
    """True while this point still has work in flight, without starting new work."""
    key = analysis_key(lat, lon)
    if key in st.session_state["analysis_results"] or key in st.session_state["analysis_failures"]:
        return False
    future: Future[Any] | None = st.session_state["analysis_jobs"].get(key)
    return future is None or not future.done()


def _intelligence_body(lat: float, lon: float) -> None:
    data, pending = current_analysis(lat, lon)
    engine_status(data)
    failure = st.session_state["analysis_failures"].get(analysis_key(lat, lon))
    if pending:
        st.info(tr("analysis_running"), icon="⏳")
    elif failure == "timeout":
        st.warning(tr("analysis_timeout"))
    elif failure is not None:
        st.warning(tr("analysis_failed"))
    dashboard(data, pending)
    feasibility_dashboard(data)


@st.fragment(run_every=1.0)
def _intelligence_panel_polling(lat: float, lon: float) -> None:
    _intelligence_body(lat, lon)


@st.fragment
def _intelligence_panel_idle(lat: float, lon: float) -> None:
    _intelligence_body(lat, lon)


def intelligence_panel(lat: float, lon: float) -> None:
    """Refresh analysis panels independently without remounting the GIS map.

    Poll at 1 Hz only while a job is actually running. A permanent run_every kept
    repainting the panel every second forever, which is what made the map flicker
    and the app feel slow long after the analysis had finished.
    """
    if job_pending(lat, lon):
        _intelligence_panel_polling(lat, lon)
    else:
        _intelligence_panel_idle(lat, lon)


def css() -> None:
    # JetBrains Mono replaces Consolas: Consolas exists only on Windows, so every
    # Linux deployment silently fell back to a default mono that broke the console look.
    mono = '"JetBrains Mono",Consolas,monospace'
    st.markdown(f"""<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800&family=JetBrains+Mono:wght@500;600;700;800&display=swap');
    #MainMenu,footer,header{{visibility:hidden}}html,body,[class*="css"]{{font-family:Inter,"Segoe UI",Arial,sans-serif}}
    .stApp{{color:{COLORS['text']};background:
        radial-gradient(58rem 30rem at 12% -8%,#00D4FF14,transparent 60%),
        radial-gradient(50rem 28rem at 108% 12%,#249BFF10,transparent 55%),
        {COLORS['bg']}}}
    .block-container{{max-width:1600px;padding:1.4rem 2rem 2.5rem}}
    ::-webkit-scrollbar{{width:9px;height:9px}}::-webkit-scrollbar-thumb{{background:#22304a;border-radius:9px}}::-webkit-scrollbar-thumb:hover{{background:#2e4262}}::-webkit-scrollbar-track{{background:transparent}}
    [data-testid="stSidebar"]{{background:linear-gradient(180deg,#0A0D12 0%,#0B0F16 100%);border-right:1px solid {COLORS['edge']}}}
    .head{{display:flex;align-items:center;border-bottom:1px solid {COLORS['edge']};padding-bottom:1rem;margin-bottom:1rem}}
    .brand{{font-size:1.55rem;font-weight:800;letter-spacing:.08em}}
    .brand span{{background:linear-gradient(90deg,{COLORS['cyan']},{COLORS['blue']});-webkit-background-clip:text;background-clip:text;color:transparent}}
    .section{{color:{COLORS['cyan']}}}.sub,.desc{{color:{COLORS['muted']};font-size:.84rem}}
    .live{{margin-left:auto;display:flex;align-items:center;gap:.45rem;color:{COLORS['cyan']};font:700 .68rem {mono};border:1px solid #15566A;border-radius:99px;padding:.35rem .8rem;background:#00D4FF0A;box-shadow:0 0 18px #00D4FF1F inset}}
    .live::before{{content:"";width:7px;height:7px;border-radius:50%;background:{COLORS['cyan']};box-shadow:0 0 8px {COLORS['cyan']};animation:pulse 2.2s ease-in-out infinite}}
    @keyframes pulse{{0%,100%{{opacity:1;transform:scale(1)}}50%{{opacity:.35;transform:scale(.78)}}}}
    .section{{font:700 .72rem {mono};letter-spacing:.16em;margin:.8rem 0 .4rem;text-transform:uppercase;display:flex;align-items:center;gap:.55rem}}
    .section::after{{content:"";flex:1;height:1px;background:linear-gradient(90deg,{COLORS['edge']},transparent)}}
    [data-testid="stMetric"],.rf-card{{background:linear-gradient(145deg,{COLORS['panel']},#0A0D12);border:1px solid {COLORS['edge']};border-top:2px solid {COLORS['cyan']};border-radius:12px;padding:1rem;box-shadow:0 10px 28px #0004;min-height:160px;transition:transform .2s,border-color .2s,box-shadow .2s;overflow:visible}}
    [data-testid="stMetric"]:hover,.rf-card:hover{{transform:translateY(-2px);border-color:{COLORS['cyan']};box-shadow:0 14px 34px #0006,0 0 22px #00D4FF14}}
    [data-testid="stMetricValue"]{{font:700 1.3rem {mono};color:white}}
    [data-testid="stMetricValue"],[data-testid="stMetricValue"]>div{{white-space:normal!important;overflow:visible!important;text-overflow:clip!important;word-break:normal!important;overflow-wrap:anywhere!important;line-height:1.15!important;font-size:clamp(.88rem,1.25vw,1.25rem)!important;min-height:2.35em}}
    [data-testid="stMetricDelta"],[data-testid="stMetricDelta"]>div{{white-space:normal!important;overflow:visible!important;text-overflow:clip!important;line-height:1.25!important}}
    [data-testid="stMetricLabel"] p{{color:{COLORS['muted']}!important;font-size:.7rem!important;text-transform:uppercase}}
    .rf-label{{color:{COLORS['muted']};font-size:.7rem;text-transform:uppercase;margin-bottom:.8rem}}.rf-value{{color:white;font:700 clamp(.82rem,1.08vw,1.12rem)/1.22 {mono};white-space:normal;overflow-wrap:normal;word-break:keep-all;min-height:2.55em;display:flex;align-items:center}}.rf-delta{{color:{COLORS['muted']};font:600 .76rem/1.3 {mono};margin-top:.65rem}}
    .note{{background:#0A0D12;border:1px solid {COLORS['edge']};border-radius:8px;padding:.45rem .7rem;color:{COLORS['muted']};font:600 .7rem {mono};margin-top:-.45rem}}
    .riskgrid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(195px,1fr));gap:.7rem;margin:.8rem 0 1rem}}
    .riskcard{{background:linear-gradient(145deg,{COLORS['panel']},#0A0D12);border:1px solid {COLORS['edge']};border-radius:11px;padding:.9rem;min-height:175px;transition:transform .2s,box-shadow .2s}}
    .riskcard:hover{{transform:translateY(-2px);box-shadow:0 12px 30px #0006}}
    .riskhead{{color:{COLORS['muted']};font:700 .66rem {mono};letter-spacing:.08em;text-transform:uppercase}}.riskvalue{{color:white;font:800 .95rem/1.2 {mono};margin:.65rem 0}}.riskmeta{{color:{COLORS['muted']};font-size:.7rem;line-height:1.45}}
    .riskcard.good{{border-top:2px solid {COLORS['green']}}}.riskcard.warn{{border-top:2px solid #FFB020}}.riskcard.bad{{border-top:2px solid {COLORS['red']}}}.riskcard.unknown{{border-top:2px dashed {COLORS['muted']};opacity:.82}}
    .scorebox{{display:flex;align-items:center;gap:1.4rem;background:linear-gradient(120deg,#0A0D12,#0D1420);border:1px solid {COLORS['edge']};border-left:4px solid {COLORS['cyan']};border-radius:14px;padding:1.1rem 1.3rem;margin-bottom:1rem;box-shadow:0 12px 34px #0005}}
    .scorebox.unscored{{border-left-color:{COLORS['muted']}}}.scorebox.unscored .score{{color:{COLORS['muted']}}}
    .score{{font:800 2rem {mono};color:{COLORS['cyan']}}}.decision{{font:800 1.05rem {mono};color:white}}.disclaimer{{color:{COLORS['muted']};font-size:.68rem;margin-top:.35rem}}
    .ring{{--ring:{COLORS['cyan']};width:104px;height:104px;min-width:104px;border-radius:50%;display:flex;align-items:center;justify-content:center;background:conic-gradient(var(--ring) calc(var(--pct)*1%),#1B2536 0);box-shadow:0 0 24px #00D4FF1A}}
    .ring>div{{width:82px;height:82px;border-radius:50%;background:#0A0D12;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:.05rem}}
    .ring b{{font:800 1.6rem/1 {mono};color:white}}.ring i{{font:600 .58rem {mono};font-style:normal;color:{COLORS['muted']};letter-spacing:.1em}}
    .sigbar{{display:flex;gap:4px;margin-top:.5rem}}.sigbar span{{width:22px;height:6px;border-radius:3px;background:#1B2536}}.sigbar span.on{{background:{COLORS['cyan']};box-shadow:0 0 8px #00D4FF66}}
    .enginebar{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:.55rem;margin:.2rem 0 1rem}}
    .engine{{display:flex;align-items:center;gap:.5rem;background:{COLORS['panel']};border:1px solid {COLORS['edge']};border-radius:8px;padding:.55rem .7rem;font:700 .68rem {mono};color:{COLORS['muted']}}}
    .dot{{width:8px;height:8px;border-radius:50%;background:{COLORS['green']};box-shadow:0 0 8px {COLORS['green']};animation:pulse 2.6s ease-in-out infinite}}
    .dot.bad{{background:{COLORS['red']};box-shadow:0 0 8px {COLORS['red']};animation:none}}
    .stButton>button{{width:100%;border-radius:9px;border:1px solid {COLORS['edge']};background:{COLORS['panel']};color:white;font-weight:700;transition:border-color .15s,color .15s,box-shadow .15s}}
    .stButton>button:hover{{border-color:{COLORS['cyan']};color:{COLORS['cyan']};box-shadow:0 0 16px #00D4FF1F}}
    .stButton>button[kind="primary"],[data-testid="stFormSubmitButton"]>button{{background:linear-gradient(120deg,#0A3D4F,#0B2A47);border-color:#15566A}}
    .stButton>button:focus-visible,[role="radiogroup"] input:focus-visible{{outline:3px solid {COLORS['cyan']};outline-offset:2px}}
    [data-testid="stFileUploaderDropzone"]{{background:{COLORS['panel']};border-color:{COLORS['edge']}}}
    [data-testid="stDataFrame"]{{border:1px solid {COLORS['edge']};border-radius:11px}}iframe{{border:1px solid {COLORS['edge']}!important;border-radius:11px;box-shadow:none!important;background:transparent!important}}[data-testid="stCustomComponentV1"]{{box-shadow:none!important}}
    .appfooter{{border-top:1px solid {COLORS['edge']};margin-top:1.8rem;padding-top:.8rem;color:{COLORS['muted']};font:600 .68rem {mono};text-align:right}}
    @media(max-width:1100px){{.riskgrid{{grid-template-columns:repeat(2,minmax(0,1fr))}}[data-testid="stHorizontalBlock"]{{flex-wrap:wrap}}[data-testid="column"]{{min-width:240px!important;flex:1 1 calc(50% - 1rem)!important}}}}
    @media(max-width:800px){{.block-container{{padding:1rem}}.head{{align-items:flex-start;flex-direction:column;gap:.6rem}}.live{{margin-left:0}}.enginebar,.riskgrid{{grid-template-columns:1fr}}.scorebox{{align-items:flex-start;flex-direction:column;gap:.6rem}}[data-testid="column"]{{min-width:100%!important;flex:1 1 100%!important}}}}
    @media(prefers-reduced-motion:reduce){{*,*::before,*::after{{scroll-behavior:auto!important;transition:none!important;animation:none!important}}}}
    </style>""", unsafe_allow_html=True)


def section(key: str, description: str | None = None) -> None:
    extra = f'<div class="desc">{html.escape(tr(description))}</div>' if description else ""
    st.markdown(f'<div class="section">{html.escape(tr(key))}</div>{extra}', unsafe_allow_html=True)


def legend() -> str:
    rows = [(COLORS["blue"], tr("target_legend")), (COLORS["red"], tr("bts_legend")), (COLORS["green"], tr("built_legend"))]
    items = "".join(f'<div style="margin:6px 0"><i style="display:inline-block;width:10px;height:10px;border-radius:50%;background:{color};margin-right:8px"></i>{html.escape(label)}</div>' for color, label in rows)
    return f'<div style="position:fixed;bottom:22px;right:14px;z-index:9999;background:#0A0D12ee;color:white;border:1px solid {COLORS["edge"]};border-left:3px solid {COLORS["cyan"]};border-radius:9px;padding:10px 13px;font:600 11px Inter"><b style="color:{COLORS["cyan"]}">{html.escape(tr("legend"))}</b>{items}</div>'


def map_style() -> str:
    """Remove Leaflet's heavy default shadows while preserving clear controls."""
    return """<style>
    .leaflet-container,.leaflet-control,.leaflet-control-layers,
    .leaflet-bar a,.leaflet-popup-content-wrapper,.leaflet-popup-tip {
        box-shadow: none !important;
    }
    .leaflet-control-layers,.leaflet-bar a {
        border-color: #263142 !important;
    }
    </style>"""


def instant_click_marker(map_name: str) -> str:
    """Show click feedback immediately while Streamlit persists the point."""
    return f"""(function () {{
        const map = {map_name};
        let pendingMarker = null;
        map.on("click", function (event) {{
            if (pendingMarker) map.removeLayer(pendingMarker);
            pendingMarker = L.circleMarker(event.latlng, {{
                radius: 7,
                color: "{COLORS['cyan']}",
                weight: 2,
                fill: true,
                fillColor: "{COLORS['blue']}",
                fillOpacity: 0.75,
                interactive: false
            }}).addTo(map);
        }});
    }})();"""


def build_map(data: Mapping[str, Mapping[str, Any]] | None, active_index: int = -1) -> folium.Map:
    points = st.session_state["target_points"]
    map_view = st.session_state.get("map_view")
    center = ([map_view["lat"], map_view["lon"]] if map_view else
              [points[-1]["lat"], points[-1]["lon"]] if points else DEFAULT_CENTER)
    fmap = folium.Map(location=center, zoom_start=14 if (points or map_view) else DEFAULT_ZOOM,
                      tiles=None, control_scale=True, prefer_canvas=True)
    folium.TileLayer("OpenStreetMap", name=tr("osm"), show=True).add_to(fmap)
    folium.TileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}", attr="Esri, Maxar, Earthstar Geographics", name=tr("sat"), show=False).add_to(fmap)
    targets = folium.FeatureGroup(name=tr("targets"), show=True)
    for number, point in enumerate(points, 1):
        selected = number - 1 == active_index
        popup = f"<b>{html.escape(tr('point'))} {number}</b><br>{html.escape(tr('lat'))}: {point['lat']:.6f}<br>{html.escape(tr('lon'))}: {point['lon']:.6f}"
        # The active point is drawn larger and in white so it stands out among many.
        folium.CircleMarker([point["lat"], point["lon"]], radius=10 if selected else 7,
                            color="#FFFFFF" if selected else COLORS["cyan"], weight=3 if selected else 2,
                            fill=True, fill_color=COLORS["blue"], fill_opacity=.9 if selected else .6,
                            popup=popup, tooltip=tr("target_tip", number=number)).add_to(targets)
    targets.add_to(fmap)
    built = folium.FeatureGroup(name=tr("built_layer"), show=True)
    if points and data and data["gee"].get("land_cover") == 50:
        # Anchor to the analysed point, not the map centre — after a location search
        # `center` is the search result and the circle landed away from the target.
        anchor = points[active_index] if 0 <= active_index < len(points) else points[-1]
        analysed = [anchor["lat"], anchor["lon"]]
        folium.Circle(analysed, radius=500, color=COLORS["green"], fill=True, fill_opacity=.1, tooltip=tr("built_tip")).add_to(built)
    built.add_to(fmap)
    towers = folium.FeatureGroup(name=tr("bts_layer"), show=True)
    # Only plot a tower we actually measured — no marker when OpenCelliD has nothing.
    if data and data["rf"].get("available") and data["rf"].get("tower_lat") is not None:
        rf = data["rf"]; distance_text = tr("meters", value=f"{rf['distance']:.0f}")
        popup = f"<b>{html.escape(str(rf['tower_id']))}</b><br>{html.escape(tr('tower_distance', value=distance_text))}"
        folium.CircleMarker([rf["tower_lat"], rf["tower_lon"]], radius=7, color=COLORS["red"], fill=True, fill_color=COLORS["red"], fill_opacity=.75, popup=popup, tooltip=tr("bts_tip", tower=rf["tower_id"])).add_to(towers)
    towers.add_to(fmap)
    proposals = folium.FeatureGroup(name=tr("recommend"), show=True)
    found = st.session_state.get("recommendations") or {}
    for rank, candidate in enumerate(found.get("candidates") or [], 1):
        # Amber diamonds, visually distinct from blue targets and red existing towers.
        folium.RegularPolygonMarker(
            [candidate["lat"], candidate["lon"]], number_of_sides=4, rotation=45, radius=9,
            color="#FFB020", weight=2, fill=True, fill_color="#FFB020", fill_opacity=.55,
            tooltip=tr("recommend_tip", rank=rank, people=f'{candidate["unmet_people"]:,.0f}'),
        ).add_to(proposals)
    proposals.add_to(fmap)
    Fullscreen(position="topleft").add_to(fmap); folium.LayerControl(position="topright").add_to(fmap)
    if map_view and map_view.get("bounds"):
        fmap.fit_bounds(map_view["bounds"], padding=(35, 35), max_zoom=16)
    # get_root() is annotated as Element but returns a Figure, which is what carries
    # .html and .script. Narrow it once rather than ignoring three separate lines.
    root: Any = fmap.get_root()
    root.html.add_child(folium.Element(map_style()))
    root.html.add_child(folium.Element(legend()))
    root.script.add_child(folium.Element(instant_click_marker(fmap.get_name())))
    return fmap


def handle_click(output: Mapping[str, Any] | None) -> None:
    if not output:
        return
    # Clicking an existing marker selects that point for analysis instead of
    # adding a new one on top of it.
    marker = output.get("last_object_clicked")
    if isinstance(marker, Mapping) and marker.get("lat") is not None and marker.get("lng") is not None:
        target = coord_key(marker["lat"], marker["lng"])
        for index, point in enumerate(st.session_state["target_points"]):
            if coord_key(point["lat"], point["lon"]) == target:
                if st.session_state.get("selected_point") != index:
                    st.session_state["selected_point"] = index
                    st.rerun()
                return
    click = output.get("last_clicked")
    if not isinstance(click, Mapping) or click.get("lat") is None or click.get("lng") is None: return
    signature = coord_key(click["lat"], click["lng"])
    if signature == st.session_state["last_click"]: return
    st.session_state["last_click"] = signature; result = add_point(*signature, "map")
    if result == "added":
        st.session_state["map_view"] = None
        # Jump straight to the point just created.
        st.session_state["selected_point"] = len(st.session_state["target_points"]) - 1
    if result != "added": notice("warning" if result in ("limit", "duplicate") else "error", result)
    st.rerun()


def number(value: float | None, decimals: int = 0) -> str:
    return tr("unavailable") if value is None else f"{value:,.{decimals}f}"


def cover_name(code: int | None) -> str:
    return tr("unavailable") if code is None else tr(LAND_KEYS[code]) if code in LAND_KEYS else tr("unknown_land", code=code)


def dashboard(data: Mapping[str, Mapping[str, Any]] | None, pending: bool = False) -> None:
    section("dashboard", "dashboard_desc")
    if not data:
        if not pending:
            st.info(tr("start"))
        return
    rf, gee_data, road = data["rf"], data["gee"], data["road"]
    if not all(item.get("available") for item in (rf, gee_data, road)): st.warning(tr("partial"))
    columns = st.columns(4)
    with columns[0]:
        state = rf.get("status")
        status = tr("greenfield") if state == "greenfield" else tr("collocation") if state else tr("unavailable")
        distance = number(rf.get("distance"))
        distance_label = tr("meters", value=distance) if rf.get("distance") is not None else distance
        # Spell out the rule behind the verdict: "COLLOCATION PRIORITY / 266 m" alone
        # never said what to do or why 266 m produced that answer.
        if rf.get("no_tower"):
            status = tr("no_tower")
            reason = tr("no_tower_why", radius=OPENCELLID_SEARCH_KM)
        elif state == "greenfield":
            reason = tr("greenfield_why", distance=distance_label, radius=COLLOCATION_RADIUS_M)
        elif state:
            reason = tr("collocation_why", distance=distance_label, radius=COLLOCATION_RADIUS_M)
        else:
            reason = tr("rf_unknown_why")
        st.caption(tr("rf"))
        st.markdown(
            '<div class="rf-card">'
            f'<div class="rf-label">{html.escape(tr("deployment"))}</div>'
            f'<div class="rf-value">{html.escape(status)}</div>'
            f'<div class="rf-delta">↳ {html.escape(reason)}</div>'
            '</div>',
            unsafe_allow_html=True,
        )
        # Every id shown here is a measured OpenCelliD cell; there is no synthetic branch.
        if rf.get("tower_id"):
            tower_note = tr("tower_id", value=rf["tower_id"])
        elif rf.get("no_tower"):
            tower_note = tr("no_tower_why", radius=OPENCELLID_SEARCH_KM)
        else:
            tower_note = rf.get("error") or tr("rf_no_key")
        st.markdown(f'<div class="note">{html.escape(tower_note)}</div>', unsafe_allow_html=True)
    with columns[1]:
        st.caption(tr("terrain")); st.metric(tr("elevation"), tr("meters", value=number(gee_data.get("elevation"))), tr("slope", value=number(gee_data.get("slope"), 1)))
    with columns[2]:
        st.caption(tr("commercial")); st.metric(tr("population"), number(gee_data.get("population")), tr("cover", value=cover_name(gee_data.get("land_cover"))))
        if gee_data.get("fallback"):
            st.markdown(f'<div class="note">{html.escape(tr("estimated"))}</div>', unsafe_allow_html=True)
    with columns[3]:
        st.caption(tr("access"))
        if road.get("no_road"):
            st.metric(tr("road_distance"), tr("no_road_value"), tr("no_road_hint"))
        else:
            st.metric(tr("road_distance"), tr("meters", value=number(road.get("distance"))), tr("road_type", value=road.get("road_type") or tr("unknown_road")))
        st.markdown(f'<div class="note">{html.escape(tr("highway", value=road.get("highway") or tr("not_mapped")))}</div>', unsafe_allow_html=True)


def distance_text(value: float | None) -> str:
    if value is None:
        return tr("not_mapped")
    return tr("meters", value=f"{value:,.0f}") if value < 1000 else tr("kilometers", value=f"{value / 1000:,.1f}")


def feasibility_dashboard(data: Mapping[str, Mapping[str, Any]] | None) -> None:
    """Render telco-specific commercial and engineering decision intelligence."""
    section("feasibility", "feasibility_desc")
    if not data:
        return
    gee_data, context, wind = data["gee"], data["context"], data["wind"]
    road, decision = data["road"], data["decision"]
    # "unknown" is its own visual state. Painting an unscreened constraint green was
    # what let a point with no data at all look like a healthy site.
    permit_class = ("unknown" if decision["permit"] == "unknown" else
                    "bad" if decision["permit"] in {"high", "restricted"} else
                    "warn" if decision["permit"] == "medium" else "good")
    power_class = "bad" if decision["off_grid"] else "good"
    wind_class = ("unknown" if not wind.get("tower_class") else
                  "bad" if wind["tower_class"] == "heavy" else
                  "warn" if wind["tower_class"] == "reinforced" else "good")
    flood_class = ("unknown" if decision["flood"] == "unknown" else
                   "bad" if decision["flood"] == "high" else
                   "warn" if decision["flood"] == "medium" else "good")
    market_class = ("unknown" if decision["market"] == "unknown" else
                    "good" if decision["market"] == "high" else
                    "warn" if decision["market"] == "medium" else "bad")
    access_class = ("unknown" if decision["access"] == "unknown" else
                    "bad" if decision["access"] == "none" else
                    "warn" if decision["access"] == "far" or decision["terrain"] == "steep" else "good")
    permit_value = tr(f"permit_{decision['permit']}")
    power_value = tr("off_grid") if decision["off_grid"] else tr("grid_connected")
    tower_value = tr(f"tower_{wind.get('tower_class')}") if wind.get("tower_class") else tr("unavailable")
    flood_value = tr(f"risk_{decision['flood']}")
    market_value = tr(f"market_{decision['market']}")
    access_value = tr(f"access_{decision['access']}")
    terrain_note = tr(f"terrain_{decision['terrain']}")
    slope_text = (tr("slope", value=number(gee_data.get("slope"), 1))
                  if gee_data.get("slope") is not None else tr("unavailable"))
    road_text = (tr("no_road_value") if road.get("no_road")
                 else distance_text(road.get("distance")) if road.get("available") else tr("not_mapped"))
    types = context.get("poi_types", {})
    cards = [
        (permit_class, "land_permit", permit_value,
         f"{tr('land_value', value=cover_name(gee_data.get('land_cover')))}<br>{tr(decision['permit_note'])}"),
        (access_class, "access_terrain", access_value,
         f"{tr('access_meta', road=road_text)}<br>"
         f"{tr('terrain_meta', slope=slope_text)}<br>{terrain_note}"
         + (f"<br>⚠ {tr('access_none_note')}" if decision["access"] == "none"
            else f"<br>⚠ {tr('access_far_note')}" if decision["access"] == "far" else "")),
        (power_class, "power_access", power_value,
         f"{tr('power_distance', value=distance_text(context.get('power_distance')))}<br>{tr('power_assets', value=context.get('power_count', 0))}" +
         (f"<br>⚠ {tr('offgrid_warning')}" if decision["off_grid"] else "")),
        (wind_class, "wind_hazard", tower_value,
         f"{tr('max_gust')}: {tr('wind_value', value=number(wind.get('max_gust'), 1))}<br>{tr('wind_source')}"),
        (flood_class, "flood_risk", flood_value,
         f"{tr('water_distance', value=distance_text(context.get('water_distance')))}<br>" +
         (tr('water_occurrence', value=number(gee_data.get('water_occurrence'), 1)) if gee_data.get('water_occurrence') is not None else tr('data_hybrid')) +
         f"<br>{tr('flood_high_action' if decision['flood'] == 'high' else 'flood_review' if decision['flood'] == 'medium' else 'flood_clear')}"),
        (market_class, "market_poi", market_value,
         f"{tr('poi_value', value=context.get('poi_count', 0))}<br>{tr('poi_mix', schools=types.get('school', 0), universities=types.get('university', 0), hospitals=types.get('hospital', 0), markets=types.get('marketplace', 0))}"),
    ]
    card_html = "".join(
        f'<div class="riskcard {style}"><div class="riskhead">{html.escape(tr(title))}</div>'
        f'<div class="riskvalue">{html.escape(value)}</div><div class="riskmeta">{details}</div></div>'
        for style, title, value, details in cards
    )
    st.markdown(f'<div class="riskgrid">{card_html}</div>', unsafe_allow_html=True)
    known, total = decision["known_signals"], decision["total_signals"]
    scored = decision["score"] is not None
    note = (tr("score_note") if scored else tr("insufficient_note", known=known, total=total))
    # Score ring: filled fraction is the score itself, colour follows the verdict so the
    # gauge and the recommendation can never disagree.
    ring_colors = {"approve": COLORS["green"], "review": "#FFB020", "avoid": COLORS["red"]}
    ring_color = ring_colors.get(decision["recommendation"], COLORS["muted"])
    ring = (
        f'<div class="ring" style="--pct:{decision["score"] if scored else 0};--ring:{ring_color}">'
        f'<div><b>{decision["score"] if scored else "—"}</b><i>/100</i></div></div>'
    )
    signals = "".join(f'<span{" class=on" if i < known else ""}></span>' for i in range(total))
    st.markdown(
        f'<div class="scorebox{"" if scored else " unscored"}">{ring}<div>'
        f'<div class="riskhead">{html.escape(tr("site_score"))} · {html.escape(tr("recommendation"))}</div>'
        f'<div class="decision">{html.escape(tr(decision["recommendation"]))}</div>'
        f'<div class="disclaimer">{html.escape(tr("confidence_value", known=known, total=total))}</div>'
        f'<div class="sigbar">{signals}</div>'
        f'<div class="disclaimer">{html.escape(note)}</div></div></div>', unsafe_allow_html=True)
    if scored and known < total:
        st.caption(f'⚠ {tr("partial_signals", missing=total - known)}')


def score_distribution_chart(points: Sequence[Mapping[str, Any]]) -> None:
    """Render a bar chart of site scores across all analysed points."""
    rows = []
    for index, point in enumerate(points, 1):
        stored = st.session_state["analysis_results"].get(analysis_key(point["lat"], point["lon"]))
        decision = (stored or {}).get("decision") or {}
        score = decision.get("score")
        if score is not None:
            rows.append({"Point": index, "Score": score,
                         "Verdict": tr(decision.get("recommendation", "queued"))})
    if not rows:
        return
    chart_data = pd.DataFrame(rows)
    chart = alt.Chart(chart_data).mark_bar().encode(
        x=alt.X("Point:Q", title=tr("point")),
        y=alt.Y("Score:Q", title=tr("score"), scale=alt.Scale(domain=[0, 100])),
        color=alt.Color("Verdict:N", scale=alt.Scale(
            domain=[tr("verdict_approve"), tr("verdict_review"), tr("verdict_avoid"), tr("verdict_insufficient")],
            range=[COLORS["green"], "#FFB020", COLORS["red"], COLORS["muted"]])),
        tooltip=[alt.Tooltip("Point:Q", title=tr("point")),
                 alt.Tooltip("Score:Q", title=tr("score")),
                 alt.Tooltip("Verdict:N", title=tr("verdict"))],
    ).properties(height=250)
    st.altair_chart(chart, use_container_width=True)


def feature_comparison_chart(points: Sequence[Mapping[str, Any]]) -> None:
    """Render a scatter plot comparing elevation vs population for analysed sites."""
    rows = []
    for index, point in enumerate(points, 1):
        stored = st.session_state["analysis_results"].get(analysis_key(point["lat"], point["lon"]))
        if not stored:
            continue
        gee = stored.get("gee", {})
        elevation, population = gee.get("elevation"), gee.get("population")
        if elevation is not None and population is not None:
            rows.append({"Point": index, "Elevation": elevation, "Population": population})
    if len(rows) < 2:
        return
    chart_data = pd.DataFrame(rows)
    chart = alt.Chart(chart_data).mark_circle(size=80).encode(
        x=alt.X("Elevation:Q", title=tr("elevation")),
        y=alt.Y("Population:Q", title=tr("population")),
        color=alt.Color("Point:N", scale=alt.Scale(scheme="category10")),
        tooltip=[alt.Tooltip("Point:N", title=tr("point")),
                 alt.Tooltip("Elevation:Q", title=tr("elevation")),
                 alt.Tooltip("Population:Q", title=tr("population"))],
    ).properties(height=250)
    st.altair_chart(chart, use_container_width=True)


def engine_status(data: Mapping[str, Mapping[str, Any]] | None) -> None:
    """Render an accessible, compact health summary for external engines.

    When no analysis has run, the honest state is NOT CHECKED — never ONLINE. Reporting
    ONLINE before any provider has answered created false confidence that every engine
    was healthy when nothing had actually been contacted.
    """
    if data is None:
        states = [
            ("osm_engine", False, "not_checked"),
            ("rf_engine", False, "not_checked"),
            ("gee_engine", False, "not_checked"),
        ]
    else:
        states = [
            ("osm_engine", bool(data and data["road"].get("available")), "online"),
            ("rf_engine", bool(data and data["rf"].get("available")), "online"),
            ("gee_engine", bool(data and data["gee"].get("available")), "fallback" if data and data["gee"].get("fallback") else "online"),
        ]
    items = "".join(
        f'<div class="engine"><span class="dot{" bad" if not ready and status_key != "not_checked" else ""}"></span>'
        f'{html.escape(tr(key))} · '
        f'{html.escape(tr(status_key if ready or status_key == "not_checked" else "degraded"))}</div>'
        for key, ready, status_key in states
    )
    st.markdown(
        f'<div class="section">{html.escape(tr("engine_status"))}</div>'
        f'<div class="enginebar" role="status" aria-live="polite">{items}</div>',
        unsafe_allow_html=True,
    )


def terminal() -> None:
    section("terminal"); st.metric(tr("total"), len(st.session_state["target_points"]))
    if not st.session_state["target_points"]: st.info(tr("empty_table")); return
    labels = {"map": tr("map_click"), "upload": tr("file_upload"), "demo": tr("demo_source"),
              "manual": tr("manual_source")}
    rows = [{tr("point"): index, tr("lat"): p["lat"], tr("lon"): p["lon"], tr("timestamp"): p.get("timestamp", tr("unavailable")), tr("source"): labels.get(p.get("source"), tr("unavailable"))} for index, p in enumerate(st.session_state["target_points"], 1)]
    registry = pd.DataFrame(rows)
    st.dataframe(registry, use_container_width=True, hide_index=True, column_config={tr("lat"): st.column_config.NumberColumn(format="%.6f"), tr("lon"): st.column_config.NumberColumn(format="%.6f")})
    export_button(registry, "points", "export_points")


def main() -> None:
    initialize_state(); css()
    if not require_authentication():
        return
    with st.sidebar:
        section("control")
        label_language = st.session_state.get("language", "EN")
        codes: list[str] = list(TEXT)
        # Label each option in the language currently selected, not in its own language.
        selected = st.radio(tr("language"), codes, index=codes.index(label_language),
                            format_func=lambda code: TEXT[label_language][code.lower()],
                            horizontal=True, key="language_radio")
        if selected != st.session_state["language"]: st.session_state["language"] = selected; st.rerun()
        section("location_search")
        selected_location = st_searchbox(
            location_suggestions,
            placeholder=tr("search_placeholder"), label=tr("search_location"),
            key=f"osm_location_autocomplete_{st.session_state['language']}",
            debounce=350, edit_after_submit="option", clear_on_submit=False,
            rerun_on_update=False,
            style_overrides={"searchbox": {"menuList": {"maxHeight": "320px"},
                                           "option": {"whiteSpace": "normal", "lineHeight": "1.3"}}},
        )
        st.caption(tr("search_hint"))
        selected_identity = ((selected_location.get("osm_type"), selected_location.get("osm_id"),
                              selected_location.get("lat"), selected_location.get("lon"))
                             if selected_location else None)
        if selected_location and selected_identity != st.session_state.get("active_location_identity"):
            st.session_state["active_location_identity"] = selected_identity
            focus_location(selected_location)
            st.rerun()
        manual_entry()
        section("ingest")
        upload = st.file_uploader(tr("upload"), type=["csv", "xlsx"], help=tr("upload_help"), key=f"upload_{st.session_state['upload_version']}")
        if upload is not None: ingest_file(upload)
        st.button(tr("demo_jakarta"), on_click=load_jakarta_demo, use_container_width=True, type="primary")
        st.button(tr("clear"), on_click=reset_state, use_container_width=True)
        st.caption(tr("capacity", used=len(st.session_state["target_points"]), maximum=MAX_POINTS))
    brand = html.escape(tr("brand"))
    st.markdown(f'<div class="head"><div><div class="brand">{brand[:4]}<span>{brand[4:]}</span></div><div class="sub">{html.escape(tr("subtitle"))}</div></div><div class="live">● {html.escape(tr("live"))}</div></div>', unsafe_allow_html=True)
    render_notices(); map_data = None; active = None
    points = st.session_state["target_points"]
    index = active_point_index()
    if points:
        active = points[index]
        harvest_analyses()
        map_data, _ = current_analysis(active["lat"], active["lon"])
        # Queue every other point too, so the per-point scorecard fills in rather
        # than only scoring whichever point happens to be open.
        for other in points:
            queue_analysis(other["lat"], other["lon"])
    if active is None:
        engine_status(None)
    section("map", "map_desc")
    try:
        output = st_folium(build_map(map_data, index), height=590,
                           returned_objects=["last_clicked", "last_object_clicked"],
                           use_container_width=True,
                           key=f"omnisite_map_{st.session_state['map_revision']}")
        handle_click(output)
    except Exception as exc:
        LOGGER.exception("Map rendering failed: %s", exc)
        st.error(tr("map_error"))
    recommendation_panel(active)
    point_navigator()
    if active:
        if len(points) > 1:
            st.caption(tr("viewing_point", index=index + 1, total=len(points)))
        intelligence_panel(active["lat"], active["lon"])
    else:
        dashboard(None)
        feasibility_dashboard(None)
    terminal()
    st.markdown(f'<div class="appfooter">{html.escape(tr("footer"))}</div>',
                unsafe_allow_html=True)


if __name__ == "__main__":
    main()
