"""
global_cn.py — 전지구 CN 분석 엔진 (API 기반, 로컬 데이터 불필요)

로컬 파일 없이 두 개의 공개 API에서 실시간으로 래스터를 가져온다:

  1. SoilGrids WCS (ISRIC)
       URL: https://maps.isric.org/mapserv?map=/map/clay.map
       인증: 불필요 | 응답: GeoTIFF (BytesIO)
       → clay(%) + sand(%) → USDA 텍스처 클래스 → HSG(A/B/C/D)

  2. ESA WorldCover v2.0 2021 (AWS S3 공개 버킷)
       URL: https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map/{tile}.tif
       인증: 불필요 | 접근: rasterio + GDAL vsicurl (COG range request)
       → 10m 해상도, 3°×3° 타일, 11개 토지피복 클래스

사용 패키지:
  - rasterio   (래스터 읽기 / COG 원격 접근)
  - requests   (SoilGrids WCS HTTP 요청)
  - numpy, geopandas, shapely, pyproj (기존 종속성, 추가 불필요)
"""

import os
import io
import uuid as _uuid_mod
from io import BytesIO
from collections import Counter
from datetime import datetime

import numpy as np

try:
    import geopandas as gpd
    from shapely.geometry import mapping
    from shapely.ops import transform as shapely_transform
    from pyproj import Geod, Transformer
    import rasterio
    from rasterio.mask import mask as rio_mask
    import requests
    API_DEPS_AVAILABLE = True
except ImportError as _e:
    gpd = None
    API_DEPS_AVAILABLE = False
    _API_IMPORT_ERROR = str(_e)

from .global_cn_tables import (
    WORLDCOVER_CN,
    WORLDCOVER_NAMES,
    HYSOGS_VALUE_TO_LETTER,
    WORLDCOVER_DISCLAIMERS,
    DATA_SOURCES,
)


# ═══════════════════════════════════════════════════════════════
#  API 엔드포인트 설정
# ═══════════════════════════════════════════════════════════════

# SoilGrids WCS 2.0 (ISRIC)
SOILGRIDS_WCS_BASE = "https://maps.isric.org/mapserv?map=/map/{prop}.map"
SOILGRIDS_WCS_PARAMS = (
    "SERVICE=WCS&VERSION=2.0.1&REQUEST=GetCoverage"
    "&COVERAGEID={coverage}"
    "&FORMAT=image/tiff"
    "&SUBSETTINGCRS=EPSG:4326"
    "&SUBSET=X({minx},{maxx})"
    "&SUBSET=Y({miny},{maxy})"
)
# 사용 coverage: clay/sand 0-5cm 평균 (최상층 표토, 유출에 가장 큰 영향)
SOILGRIDS_CLAY_COVERAGE = "clay_0-5cm_mean"
SOILGRIDS_SAND_COVERAGE = "sand_0-5cm_mean"

# ESA WorldCover 2021 — AWS S3 공개 버킷 (인증 불필요)
WORLDCOVER_S3_BASE = (
    "https://esa-worldcover.s3.eu-central-1.amazonaws.com"
    "/v200/2021/map"
)
# 타일 파일명: ESA_WorldCover_10m_2021_v200_N{lat:02d}E{lon:03d}_MAP.tif
# (남위·서경은 S, W 사용)

# HTTP 요청 타임아웃 (초)
HTTP_TIMEOUT = 30

# GDAL 원격 COG 최적화 환경 설정
GDAL_REMOTE_ENV = {
    "CPL_VSIL_CURL_CHUNK_SIZE": "524288",    # 512KB 청크 (HTTP range 요청 단위)
    "GDAL_HTTP_MULTIRANGE": "YES",            # 병렬 HTTP range 요청
    "GDAL_HTTP_MERGE_CONSECUTIVE_RANGES": "YES",
    "CPL_VSIL_CURL_CACHE_SIZE": "134217728",  # 128MB HTTP 캐시
    "VSI_CACHE": "YES",
    "VSI_CACHE_SIZE": "10485760",             # 10MB 가상 파일시스템 캐시
    "GDAL_CACHEMAX": "256",                   # 256MB 래스터 블록 캐시
}


# ═══════════════════════════════════════════════════════════════
#  SoilGrids WCS — clay/sand → HSG 변환
# ═══════════════════════════════════════════════════════════════

def _fetch_soilgrids_wcs(coverage, prop, bounds_4326):
    """
    SoilGrids WCS에서 bbox에 해당하는 GeoTIFF를 BytesIO로 반환.
    coverage: e.g. "clay_0-5cm_mean"
    prop: e.g. "clay"
    bounds_4326: (minx, miny, maxx, maxy)
    """
    minx, miny, maxx, maxy = bounds_4326
    base_url = SOILGRIDS_WCS_BASE.format(prop=prop)
    params   = SOILGRIDS_WCS_PARAMS.format(
        coverage=coverage,
        minx=minx, maxx=maxx,
        miny=miny, maxy=maxy,
    )
    url = f"{base_url}&{params}"

    try:
        resp = requests.get(url, timeout=HTTP_TIMEOUT, stream=True)
        resp.raise_for_status()
    except requests.exceptions.Timeout:
        raise TimeoutError(f'SoilGrids WCS 응답 시간 초과 ({HTTP_TIMEOUT}초). 네트워크 연결을 확인하세요.')
    except requests.exceptions.ConnectionError:
        raise ConnectionError('SoilGrids WCS 서버에 연결할 수 없습니다. 인터넷 연결을 확인하세요.')
    except requests.exceptions.HTTPError as e:
        raise RuntimeError(f'SoilGrids WCS 오류: {e}')

    content = resp.content
    if len(content) < 100:
        raise ValueError(f'SoilGrids WCS 응답 데이터 없음 (bbox: {bounds_4326})')

    return BytesIO(content)


def _soilgrids_pixel_to_pct(raw_array):
    """
    SoilGrids WCS 픽셀 값 → 백분율(%) 변환.
    SoilGrids 저장 형식: 실제 값(g/kg) × 10 → 정수
    clay g/kg / 10 = % (1000 g/kg = 100%)
    따라서: pixel_value / 10 / 10 = % → pixel_value / 100 = %
    """
    return raw_array.astype(np.float32) / 100.0


def _texture_to_hsg(clay_pct, sand_pct):
    """
    USDA 텍스처 클래스 기반 HSG 판별 (Rawls et al. 1982 단순화).
    픽셀 단위 numpy 벡터 연산 지원.

    clay_pct, sand_pct: 0~100 float (%) numpy array 또는 scalar

    반환: HSG 정수 코드 array (1=A, 2=B, 3=C, 4=D)
    """
    clay = np.asarray(clay_pct, dtype=np.float32)
    sand = np.asarray(sand_pct, dtype=np.float32)

    # 초기화: 모두 B (중간값)
    hsg = np.full_like(clay, 2, dtype=np.int8)

    # A: 모래 우세 (sand ≥ 70%, clay < 10%)
    hsg = np.where((sand >= 70) & (clay < 10), 1, hsg)
    # D: 점토 우세 (clay ≥ 40%)
    hsg = np.where(clay >= 40, 4, hsg)
    # C: clay 20~40% 범위
    hsg = np.where((clay >= 20) & (clay < 40), 3, hsg)
    # B: 나머지 (clay 10~20%, sand 25~70% 등)
    # → 초기화값 2 그대로

    return hsg


def _fetch_hsg_raster(polygon_geom_4326):
    """
    SoilGrids WCS에서 clay + sand를 받아 HSG 픽셀 배열 반환.
    반환: 1D numpy array of HSG integer codes (1=A, 2=B, 3=C, 4=D)
    """
    bounds = polygon_geom_4326.bounds  # (minx, miny, maxx, maxy)

    # Clay 래스터 취득
    clay_buf = _fetch_soilgrids_wcs(SOILGRIDS_CLAY_COVERAGE, "clay", bounds)
    with rasterio.open(clay_buf) as src:
        out_clay, _ = rio_mask(src, [mapping(polygon_geom_4326)],
                               crop=True, all_touched=True, nodata=src.nodata)
        clay_raw = out_clay[0]
        nd = src.nodata if src.nodata is not None else -32768
        clay_valid_mask = clay_raw != nd
        clay_pct = _soilgrids_pixel_to_pct(clay_raw)

    # Sand 래스터 취득
    sand_buf = _fetch_soilgrids_wcs(SOILGRIDS_SAND_COVERAGE, "sand", bounds)
    with rasterio.open(sand_buf) as src:
        out_sand, _ = rio_mask(src, [mapping(polygon_geom_4326)],
                               crop=True, all_touched=True, nodata=src.nodata)
        sand_raw = out_sand[0]
        nd_s = src.nodata if src.nodata is not None else -32768
        sand_valid_mask = sand_raw != nd_s
        sand_pct = _soilgrids_pixel_to_pct(sand_raw)

    # 유효 픽셀만 사용
    valid_mask = clay_valid_mask & sand_valid_mask
    if not valid_mask.any():
        raise ValueError('유역 내 SoilGrids 토양 데이터가 없습니다 (해양/빙하 지역 확인).')

    clay_flat = clay_pct[valid_mask]
    sand_flat = sand_pct[valid_mask]

    # HSG 코드 배열 (1~4)
    hsg_codes = _texture_to_hsg(clay_flat, sand_flat)

    # 코드 → 문자 변환 (letters used in lookup table)
    _code_to_letter = {1: 'A', 2: 'B', 3: 'C', 4: 'D'}
    hsg_letters = [_code_to_letter[int(c)] for c in hsg_codes.flatten()]

    return hsg_letters


# ═══════════════════════════════════════════════════════════════
#  ESA WorldCover — AWS S3 COG 원격 읽기
# ═══════════════════════════════════════════════════════════════

def _worldcover_tile_urls(bounds_4326):
    """
    WGS84 bounding box에 걸치는 WorldCover 타일 URL 목록 반환.
    타일 그리드: 3°×3° (S/W 코너 기준, 3의 배수로 스냅)
    """
    minx, miny, maxx, maxy = bounds_4326

    # 3° 그리드 경계 좌표 계산
    lat_start = int(miny // 3) * 3
    lat_end   = int(maxy // 3) * 3 + 3
    lon_start = int(minx // 3) * 3
    lon_end   = int(maxx // 3) * 3 + 3

    urls = []
    for lat in range(lat_start, lat_end, 3):
        for lon in range(lon_start, lon_end, 3):
            ns  = 'N' if lat >= 0 else 'S'
            ew  = 'E' if lon >= 0 else 'W'
            fname = (
                f"ESA_WorldCover_10m_2021_v200_"
                f"{ns}{abs(lat):02d}{ew}{abs(lon):03d}_MAP.tif"
            )
            url = f"/vsicurl/{WORLDCOVER_S3_BASE}/{fname}"
            urls.append((fname, url))
    return urls


def _read_worldcover_for_polygon(polygon_geom_4326):
    """
    WorldCover COG를 AWS S3에서 직접 읽어 유역 내 LC 픽셀 배열 반환.
    rasterio의 vsicurl 드라이버로 필요한 bbox 범위만 HTTP range request.
    반환: 1D numpy int16 array (유효 픽셀, 0=nodata 제외)
    """
    tile_urls = _worldcover_tile_urls(polygon_geom_4326.bounds)

    lc_parts = []
    failed   = []

    with rasterio.Env(**GDAL_REMOTE_ENV):
        for fname, url in tile_urls:
            try:
                with rasterio.open(url) as src:
                    # WorldCover CRS가 4326이 아닌 경우 대비 (실제로는 4326)
                    if src.crs and src.crs.to_epsg() != 4326:
                        t = Transformer.from_crs(4326, src.crs.to_epsg(), always_xy=True)
                        poly = shapely_transform(t.transform, polygon_geom_4326)
                    else:
                        poly = polygon_geom_4326

                    out, _ = rio_mask(src, [mapping(poly)],
                                      crop=True, all_touched=True, nodata=0)
                    data = out[0]
                    valid = data[data > 0]  # 0=nodata in WorldCover
                    if len(valid) > 0:
                        lc_parts.append(valid.astype(np.int16))
            except Exception as e:
                failed.append(f"{fname}: {e}")

    if not lc_parts:
        err_detail = "\n".join(failed) if failed else "해당 좌표에 타일 없음"
        raise ValueError(
            f'WorldCover 데이터를 가져올 수 없습니다.\n{err_detail}\n'
            '인터넷 연결 및 좌표 범위를 확인하세요.'
        )

    return np.concatenate(lc_parts)


# ═══════════════════════════════════════════════════════════════
#  핵심 CN 계산
# ═══════════════════════════════════════════════════════════════

def _calc_area_ha(polygon_geom_4326):
    """WGS84 폴리곤 면적(ha) — 측지선 기반"""
    geod = Geod(ellps='WGS84')
    area_m2, _ = geod.geometry_area_perimeter(polygon_geom_4326)
    return abs(area_m2) / 10000.0


def _compute_cn_for_polygon(polygon_geom_4326):
    """
    단일 폴리곤에 대해 CN_II 산정.

    방법: GCN250 독립 분포 비례 결합 (Jaafar et al. 2019)
      - SoilGrids WCS → clay/sand → USDA 텍스처 → HSG 픽셀 분포
      - WorldCover S3 COG → LC 픽셀 분포
      - (HSG_fraction × LC_fraction) × CN_lookup → 면적 가중 CN

    반환: (cn_ii, breakdown, matched_info)
    """
    ws_area_ha = _calc_area_ha(polygon_geom_4326)

    # ── Step A: SoilGrids WCS → HSG ─────────────────────────
    hsg_letters = _fetch_hsg_raster(polygon_geom_4326)
    if not hsg_letters:
        raise ValueError('유효한 HSG 픽셀이 없습니다.')

    # ── Step B: WorldCover COG → LC 픽셀 ────────────────────
    lc_raw = _read_worldcover_for_polygon(polygon_geom_4326)
    if len(lc_raw) == 0:
        raise ValueError('유효한 WorldCover 토지피복 픽셀이 없습니다.')

    # ── Step C: 독립 분포 비례 결합 ──────────────────────────
    total_hsg = len(hsg_letters)
    total_lc  = len(lc_raw)
    ref_total = max(total_hsg, total_lc)

    hsg_fracs = {h: c / total_hsg for h, c in Counter(hsg_letters).items()}
    lc_fracs  = {int(k): v / total_lc for k, v in Counter(lc_raw.tolist()).items()}

    breakdown      = []
    total_weighted = 0.0
    total_pixels   = 0.0

    for hsg, hf in hsg_fracs.items():
        for lc_class, lf in lc_fracs.items():
            cn_table = WORLDCOVER_CN.get(lc_class)
            if cn_table is None:
                continue
            cn_val = cn_table.get(hsg)
            if cn_val is None:
                continue

            pix     = hf * lf * ref_total
            area_ha = ws_area_ha * (hf * lf)

            total_weighted += pix * cn_val
            total_pixels   += pix

            lc_names = WORLDCOVER_NAMES.get(lc_class, {})
            breakdown.append({
                'lc_class':    lc_class,
                'lc_name_ko':  lc_names.get('ko', str(lc_class)),
                'lc_name_en':  lc_names.get('en', str(lc_class)),
                'hsg':         hsg,
                'pixel_count': round(pix),
                'cn':          cn_val,
                'area_ha':     round(area_ha, 2),
                'areaconduct': round(area_ha * cn_val, 4),
            })

    if total_pixels == 0:
        raise ValueError('유효한 (HSG, 피복) 조합이 없어 CN 산정 불가.')

    cn_ii = total_weighted / total_pixels

    # HSG 분포 요약 (보고서용)
    hsg_summary = {
        h: f"{round(f*100, 1)}%"
        for h, f in sorted(hsg_fracs.items())
    }

    matched_info = {
        'mode':            'global',
        'hsg_source':      '토양 텍스처(SoilGrids WCS, clay/sand 0-5cm) → USDA 텍스처 → HSG',
        'lc_source':       DATA_SOURCES['landcover']['full_name'],
        'hsg_pixel_count': total_hsg,
        'lc_pixel_count':  total_lc,
        'hsg_distribution': hsg_summary,
        'worldcover_tiles': [
            fname for fname, _ in _worldcover_tile_urls(polygon_geom_4326.bounds)
        ],
    }

    return cn_ii, breakdown, matched_info


# ═══════════════════════════════════════════════════════════════
#  공개 API — analyze_cn()과 동일한 인터페이스
# ═══════════════════════════════════════════════════════════════

def analyze_cn_global(watershed_gdf):
    """
    전지구 CN 분석 (API 기반).
    반환: (results, breakdown, matched_info)
    """
    if not API_DEPS_AVAILABLE:
        raise ImportError(
            'rasterio 또는 requests 패키지가 없습니다.\n'
            f'pip install rasterio requests\n원인: {_API_IMPORT_ERROR}'
        )

    ws_4326 = watershed_gdf.to_crs('EPSG:4326').copy()

    results       = []
    all_breakdown = []
    last_info     = {}

    for _, ws_row in ws_4326.iterrows():
        ws_geom    = ws_row.geometry
        ws_uuid    = str(_uuid_mod.uuid4())
        ws_attrs   = {k: v for k, v in ws_row.items() if k != 'geometry'}
        ws_area_ha = _calc_area_ha(ws_geom)

        base = {
            'uuid':          ws_uuid,
            'geometry':      ws_geom,
            'total_area_ha': round(ws_area_ha, 2),
            'data_mode':     'global',
            **ws_attrs,
        }

        try:
            cn_ii, breakdown, info = _compute_cn_for_polygon(ws_geom)
            for row in breakdown:
                row['uuid'] = ws_uuid
            all_breakdown.extend(breakdown)

            cn_amc3    = (cn_ii * 23) / (10 + 0.13 * cn_ii)
            match_area = sum(r['area_ha'] for r in breakdown)
            last_info  = info

            results.append({
                **base,
                'CN':                round(cn_ii, 2),
                'CN_AMC3':           round(cn_amc3, 2),
                'analysis_area_ha':  round(match_area, 2),
                'match_rate':        100.0,
                'unmatched_area_ha': 0.0,
                'error':             None,
                'hsg_pixel_count':   info.get('hsg_pixel_count', 0),
                'hsg_distribution':  info.get('hsg_distribution', {}),
            })
        except Exception as e:
            results.append({**base, 'CN': None, 'CN_AMC3': None, 'error': str(e)})

    return results, all_breakdown, last_info


# ═══════════════════════════════════════════════════════════════
#  보고서 생성
# ═══════════════════════════════════════════════════════════════

def _build_global_crosstab_html(breakdown, results):
    """WorldCover × HSG 크로스탭 HTML"""
    import pandas as pd

    if not breakdown:
        return '<p style="color:#666;">상세 분해 데이터가 없습니다.</p>'

    df    = pd.DataFrame(breakdown)
    uuids = df['uuid'].unique()
    parts = []

    for ws_idx, ws_uuid in enumerate(uuids):
        ws_df     = df[df['uuid'] == ws_uuid].copy()
        ws_result = next((r for r in results if r.get('uuid') == ws_uuid), {})
        ws_cn     = ws_result.get('CN')    or 0
        ws_cn3    = ws_result.get('CN_AMC3') or 0
        hsg_dist  = ws_result.get('hsg_distribution', {})

        n_total = len(uuids)
        title = (f'<h2>4-{ws_idx+1}. 유역별 계산표 (유역 {ws_idx+1})</h2>'
                 if n_total > 1 else '<h2>4. 유역별 계산표</h2>')

        # HSG 분포 주석
        hsg_note = ''
        if hsg_dist:
            dist_str = ', '.join(f'{h}: {p}' for h, p in sorted(hsg_dist.items()))
            hsg_note = (
                f'<p style="font-size:13px;color:#6d7882;margin:4px 0 12px;">'
                f'토양 HSG 분포 (SoilGrids clay/sand 기반): {dist_str}</p>'
            )

        table = '''<table style="font-size:13px;">
<tr>
  <th colspan="2" rowspan="2" style="vertical-align:middle;">피복 분류 (ESA WorldCover)</th>
  <th colspan="8">수 문 학 적  토 양 군 (SoilGrids 텍스처 기반)</th>
  <th rowspan="2" style="vertical-align:middle;">면적(ha)</th>
  <th rowspan="2" style="vertical-align:middle;">평균 CN</th>
</tr>
<tr>
  <th>A<br>면적</th><th>CN</th>
  <th>B<br>면적</th><th>CN</th>
  <th>C<br>면적</th><th>CN</th>
  <th>D<br>면적</th><th>CN</th>
</tr>
'''
        lc_groups   = ws_df.groupby(['lc_class', 'lc_name_ko'])
        total_by_h  = {h: 0.0 for h in 'ABCD'}
        total_area  = 0.0
        total_ac    = 0.0

        for (lc_class, lc_name_ko), grp in lc_groups:
            cells = ''
            row_a = 0.0
            row_c = 0.0
            for h in 'ABCD':
                sub  = grp[grp['hsg'] == h]
                a    = float(sub['area_ha'].sum())   if len(sub) else 0.0
                cn   = int(sub['cn'].iloc[0])         if len(sub) else 0
                bg   = ' style="background:#eaf6ec;"' if a > 0 else ''
                cells += f'<td{bg}>{round(a,1) if a > 0 else "0.0"}</td>'
                cells += f'<td{bg}>{cn if a > 0 else ""}</td>'
                total_by_h[h] += a
                row_a += a
                row_c += a * cn

            avg_cn_row = round(row_c / row_a, 1) if row_a > 0 else 0
            lc_en      = WORLDCOVER_NAMES.get(lc_class, {}).get('en', '')
            total_area += row_a
            total_ac   += row_c

            table += (f'<tr>'
                      f'<td style="text-align:center;">{lc_class}</td>'
                      f'<td style="text-align:left;">{lc_name_ko}'
                      f'<br><small style="color:#888;">{lc_en}</small></td>'
                      f'{cells}'
                      f'<td><strong>{round(row_a,1)}</strong></td>'
                      f'<td>{avg_cn_row if row_a > 0 else ""}</td></tr>\n')

        # 합계 행
        table += '<tr style="font-weight:700;background:var(--primary-5);">'
        table += '<td colspan="2" style="text-align:center;">면적계</td>'
        for h in 'ABCD':
            table += f'<td>{round(total_by_h[h],1)}</td><td></td>'
        table += f'<td>{round(total_area,1)}</td><td></td></tr>\n'

        # CN 결과 행
        table += ('<tr style="font-weight:700;">'
                  '<td colspan="2" rowspan="2" style="text-align:center;vertical-align:middle;">'
                  '유출곡선지수 산정</td>'
                  f'<td colspan="8" style="text-align:center;">AMC II &nbsp;:&nbsp; {ws_cn}</td>'
                  '<td colspan="2"></td></tr>\n'
                  '<tr style="font-weight:700;">'
                  f'<td colspan="8" style="text-align:center;">AMC III &nbsp;:&nbsp; {ws_cn3}</td>'
                  '<td colspan="2"></td></tr>\n'
                  '</table>\n')

        parts.append(title + hsg_note + table)

    return '\n'.join(parts)


def generate_report_html_global(results, breakdown, analysis_id, matched_info=None):
    """
    글로벌 분석 HTML 보고서 (API 기반).
    generate_report_html()과 동일한 시각 구조.
    """
    now          = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    valid        = [r for r in results if r.get('CN') is not None]
    avg_cn       = np.mean([r['CN']      for r in valid]) if valid else 0
    avg_cn3      = np.mean([r['CN_AMC3'] for r in valid]) if valid else 0
    total_area   = sum(r.get('total_area_ha', 0) for r in valid)

    # 데이터 소스 정보 박스
    src_html = ''
    if matched_info:
        tiles_str = ', '.join(matched_info.get('worldcover_tiles', ['-']))
        src_html = f"""
<div class="info-box" style="margin-bottom:24px;">
<p><strong>사용 데이터 (API 모드 — 로컬 파일 없음)</strong></p>
<p>토양(HSG): {matched_info.get('hsg_source', 'SoilGrids WCS (ISRIC)')} — 해상도 250m</p>
<p>토지피복: {matched_info.get('lc_source', DATA_SOURCES['landcover']['full_name'])} — 해상도 10m</p>
<p>HSG 픽셀: {matched_info.get('hsg_pixel_count', 0):,} | 피복 픽셀: {matched_info.get('lc_pixel_count', 0):,}</p>
<p>WorldCover 타일: {tiles_str}</p>
</div>
"""

    # 주의사항 (해당 클래스만)
    present_lc  = {r['lc_class'] for r in breakdown} if breakdown else set()
    disc_items  = ''
    for lc_class, txt in WORLDCOVER_DISCLAIMERS.items():
        if lc_class in present_lc:
            name = WORLDCOVER_NAMES.get(lc_class, {}).get('ko', str(lc_class))
            disc_items += f'<li><strong>{name}(클래스 {lc_class}):</strong> {txt}</li>\n'

    disc_html = ''
    if disc_items:
        disc_html = f"""
<div style="margin-top:16px; padding:16px 20px; background:#fff3db;
     border-left:4px solid #f59e0b; border-radius:0 8px 8px 0;">
  <p style="font-weight:700; font-size:14px; margin:0 0 8px; color:#92400e;">
    📋 글로벌 데이터 적용 주의사항
  </p>
  <ul style="font-size:13px; color:#78350f; margin:0; padding-left:20px; line-height:1.8;">
{disc_items}
    <li>토양 HSG: SoilGrids clay/sand 텍스처 기반 간접 산정 (HYSOGs250m 직접값 아님)</li>
    <li>해상도: SoilGrids 250m / WorldCover 10m — 1ha 미만 소규모 유역 신뢰도 저하 가능</li>
    <li>방법론: 독립 HSG×LC 분포 비례 결합 (GCN250, Jaafar et al. 2019)</li>
  </ul>
</div>
"""

    crosstab_html = _build_global_crosstab_html(breakdown, results)

    css = """
:root {
  --primary-50: #256ef4; --primary-60: #0b50d0; --primary-5: #ecf2fe;
  --gray-5: #f4f5f6; --gray-10: #e6e8ea; --gray-50: #6d7882;
  --gray-70: #464c53; --gray-80: #33363d; --gray-90: #1e2124;
  --success-50: #228738; --success-5: #eaf6ec;
  --danger-50: #de3412; --danger-5: #fdefec;
  --warning-5: #fff3db; --info-5: #e7f4fe; --info-50: #0b78cb;
}
* { margin:0; padding:0; box-sizing:border-box; }
body { font-family: 'Malgun Gothic', 'Apple SD Gothic Neo', sans-serif;
  font-size:17px; line-height:1.5; color: var(--gray-90); background: var(--gray-5); margin:40px; }
.report { max-width:960px; margin:0 auto; background:#fff; padding:48px; border-radius:12px;
  box-shadow: 0 1px 3px rgba(0,0,0,0.08); }
h1 { font-size:32px; font-weight:700; color:var(--gray-90); margin-bottom:8px; }
h2 { font-size:24px; font-weight:700; color:var(--gray-80); margin:40px 0 16px; }
.meta { font-size:15px; color:var(--gray-50); margin-bottom:32px; }
.badge-global { display:inline-block; padding:3px 10px; border-radius:4px; font-size:13px;
  background:#e7f4fe; color:#0b78cb; font-weight:600; margin-left:8px; }
.summary-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(160px,1fr));
  gap:16px; margin:24px 0; }
.summary-card { background:var(--primary-5); border-radius:8px; padding:20px; text-align:center; }
.summary-card .val { font-size:28px; font-weight:700; color:var(--primary-50); }
.summary-card .lbl { font-size:13px; color:var(--gray-50); margin-top:4px; }
table { border-collapse:collapse; width:100%; margin:16px 0; font-size:15px; }
th { background:var(--primary-50); color:#fff; padding:12px; text-align:center; font-weight:700; }
td { padding:10px 12px; border-bottom:1px solid var(--gray-10); text-align:center; }
tr:hover { background:var(--gray-5); }
.tag { display:inline-block; padding:2px 8px; border-radius:4px; font-size:13px; }
.tag-ok { background:var(--success-5); color:var(--success-50); }
.tag-err { background:var(--danger-5); color:var(--danger-50); }
.info-box { background:var(--info-5); border-left:4px solid var(--info-50);
  padding:20px 24px; border-radius:0 8px 8px 0; margin:20px 0; }
.info-box p { margin:6px 0; }
.formula { text-align:center; font-size:18px; margin:12px 0; font-weight:500; }
.footer { text-align:center; color:var(--gray-50); font-size:13px;
  margin-top:40px; padding-top:24px; border-top:1px solid var(--gray-10); }
"""

    # 유역별 결과 테이블 행 생성
    result_rows = ''
    for i, r in enumerate(results, 1):
        if r.get('CN') is not None:
            hd = r.get('hsg_distribution', {})
            hd_str = ' / '.join(f'{h}:{p}' for h, p in sorted(hd.items())) if hd else '-'
            result_rows += (
                f'<tr><td>{i}</td><td>{r["total_area_ha"]}</td>'
                f'<td>{r.get("analysis_area_ha","-")}</td>'
                f'<td style="font-size:12px;">{hd_str}</td>'
                f'<td><strong>{r["CN"]}</strong></td>'
                f'<td><strong>{r["CN_AMC3"]}</strong></td>'
                f'<td><span class="tag tag-ok">정상</span></td></tr>\n'
            )
        else:
            result_rows += (
                f'<tr><td>{i}</td><td>{r.get("total_area_ha","-")}</td>'
                f'<td>-</td><td>-</td><td>-</td><td>-</td>'
                f'<td><span class="tag tag-err">{r.get("error","오류")}</span></td></tr>\n'
            )

    html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<title>CN 분석 보고서 (글로벌 API) - {analysis_id[:8]}</title>
<style>{css}</style>
</head>
<body>
<div class="report">
<h1>CN (Curve Number) 분석 보고서 <span class="badge-global">🌍 글로벌 API 모드</span></h1>
<p class="meta">분석일시: {now} | 분석 ID: {analysis_id[:8]}</p>

{src_html}

<h2>1. 분석 요약</h2>
<div class="summary-grid">
  <div class="summary-card"><div class="val">{len(results)}</div><div class="lbl">총 유역 수</div></div>
  <div class="summary-card"><div class="val">{len(valid)}</div><div class="lbl">분석 성공</div></div>
  <div class="summary-card"><div class="val">{avg_cn:.1f}</div><div class="lbl">평균 CN (AMC-II)</div></div>
  <div class="summary-card"><div class="val">{avg_cn3:.1f}</div><div class="lbl">평균 CN (AMC-III)</div></div>
  <div class="summary-card"><div class="val">{total_area:,.1f}</div><div class="lbl">총 면적 (ha)</div></div>
</div>

<h2>2. 유역별 CN 분석 결과</h2>
<table>
<tr><th>No.</th><th>유역면적(ha)</th><th>분석면적(ha)</th><th>HSG 분포</th>
<th>CN(AMC-II)</th><th>CN(AMC-III)</th><th>상태</th></tr>
{result_rows}</table>

<h2>3. CN 산정 방법</h2>
<div class="info-box">
<p><strong>토양 HSG 산정 — SoilGrids WCS (ISRIC)</strong></p>
<p style="font-size:14px;">
  SoilGrids clay(%) + sand(%) (0-5cm) → USDA 텍스처 분류 → HSG(A/B/C/D) 픽셀 단위 산정<br>
  HSG 기준: clay &lt; 10% &amp; sand ≥ 70% → A | clay 10~20% → B | clay 20~40% → C | clay ≥ 40% → D
</p>
<p style="margin-top:12px;"><strong>가중평균 CN (AMC-II) — GCN250 방법론</strong></p>
<p class="formula">CN<sub>II</sub> = &Sigma;(f<sub>HSG</sub> &times; f<sub>LC</sub> &times; CN<sub>HSG,LC</sub>)</p>
<p style="font-size:14px;color:var(--gray-50);">
  f<sub>HSG</sub>: HSG 클래스별 픽셀 비율 | f<sub>LC</sub>: 토지피복 클래스별 픽셀 비율
</p>
<p style="margin-top:12px;"><strong>AMC-III 보정</strong></p>
<p class="formula">CN<sub>III</sub> = (CN<sub>II</sub> &times; 23) / (10 + 0.13 &times; CN<sub>II</sub>)</p>
<p style="font-size:14px;">출처: TR-55 (USDA 1986) | GCN250 (Jaafar et al. 2019) | SoilGrids (Poggio et al. 2021)</p>
</div>

{crosstab_html}

{disc_html}

<div style="margin-top:40px; padding:20px 24px; background:#fffbeb;
     border-left:4px solid #f59e0b; border-radius:0 8px 8px 0;">
  <p style="font-weight:700; font-size:15px; margin:0 0 8px; color:#92400e;">
    ⚠️ 베타테스트 단계 — 결과 수동 검토 필요
  </p>
  <p style="margin:0; font-size:14px; color:#78350f; line-height:1.6;">
    글로벌 모드는 SoilGrids WCS(토양) + ESA WorldCover(피복) 공개 API를 실시간으로 활용합니다.<br>
    국내 1:25,000 정밀 데이터보다 해상도가 낮으며, 실제 사업 적용 전 현장 검증이 필요합니다.
  </p>
</div>
<div class="footer">
  <p>SCS-CN 방법 기반 | SoilGrids WCS (250m) + ESA WorldCover v2.0 (10m)</p>
  <p>Poggio et al. (2021) doi:10.5194/soil-7-217-2021 |
     Zanaga et al. (2022) doi:10.5281/zenodo.7254221 |
     Jaafar et al. (2019) doi:10.1038/s41597-019-0155-x</p>
</div>
</div></body></html>"""

    return html
