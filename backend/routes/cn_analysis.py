"""
CN (Curve Number) 분석 라우트
전세계 유역에 대한 SoilGrids + ESA WorldCover 기반 CN 산정
"""
import io
import json
import uuid
from flask import Blueprint, request, jsonify

from routes.auth import token_required

cn_bp = Blueprint('cn', __name__)


def _parse_geojson_to_gdf(geojson_str):
    """GeoJSON 문자열 → GeoDataFrame (geopandas + shapely, fiona 불필요)"""
    import geopandas as gpd
    from shapely.geometry import shape

    data = json.loads(geojson_str)
    if data.get('type') == 'FeatureCollection':
        features = data['features']
    elif data.get('type') == 'Feature':
        features = [data]
    else:
        # bare geometry
        features = [{'type': 'Feature', 'geometry': data, 'properties': {}}]

    geometries = []
    props_list = []
    for f in features:
        geometries.append(shape(f['geometry']))
        props_list.append(f.get('properties') or {})

    gdf = gpd.GeoDataFrame(props_list, geometry=geometries, crs='EPSG:4326')
    return gdf


def _results_to_geojson(results, result_crs='EPSG:4326'):
    """results 리스트(geometry 포함) → GeoJSON dict"""
    try:
        import numpy as np
        import geopandas as gpd
        from shapely.geometry import mapping

        geoms = []
        props_list = []
        for r in results:
            geom = r.get('geometry')
            if geom is None:
                continue
            props = {}
            for k, v in r.items():
                if k == 'geometry':
                    continue
                if isinstance(v, float) and np.isnan(v):
                    props[k] = None
                elif isinstance(v, np.integer):
                    props[k] = int(v)
                elif isinstance(v, np.floating):
                    props[k] = float(v)
                else:
                    props[k] = v
            geoms.append(geom)
            props_list.append(props)

        if not geoms:
            return {'type': 'FeatureCollection', 'features': []}

        gdf = gpd.GeoDataFrame(props_list, geometry=geoms, crs=result_crs)
        if result_crs != 'EPSG:4326':
            gdf = gdf.to_crs('EPSG:4326')

        features = []
        for _, row in gdf.iterrows():
            p = {k: v for k, v in row.items() if k != 'geometry'}
            features.append({
                'type': 'Feature',
                'geometry': mapping(row.geometry),
                'properties': p,
            })
        return {'type': 'FeatureCollection', 'features': features}

    except Exception:
        return {'type': 'FeatureCollection', 'features': []}


def _clean_results_for_json(results):
    """geometry 제거 + numpy 타입 → Python 기본형 변환"""
    import numpy as np
    cleaned = []
    for r in results:
        item = {}
        for k, v in r.items():
            if k == 'geometry':
                continue
            if isinstance(v, float) and np.isnan(v):
                item[k] = None
            elif isinstance(v, np.integer):
                item[k] = int(v)
            elif isinstance(v, np.floating):
                item[k] = float(v)
            else:
                item[k] = v
        cleaned.append(item)
    return cleaned


@cn_bp.route('/analyze', methods=['POST'])
@token_required
def analyze(current_user):
    """
    전세계 CN 분석 엔드포인트
    force_global=true 고정 (항상 SoilGrids + ESA WorldCover 사용)
    """
    # 의존 패키지 확인
    try:
        from utils.global_cn import analyze_cn_global, API_DEPS_AVAILABLE
    except ImportError as e:
        return jsonify({
            'status': 'error',
            'message': f'CN 분석 모듈을 불러올 수 없습니다: {e}'
        }), 503

    if not API_DEPS_AVAILABLE:
        return jsonify({
            'status': 'error',
            'message': (
                'CN 분석에 필요한 패키지(rasterio)가 서버에 설치되지 않았습니다.\n'
                'pip install rasterio 를 실행하여 설치하세요.'
            )
        }), 503

    geojson_str = request.form.get('geojson')
    if not geojson_str:
        return jsonify({'status': 'error', 'message': '유역 GeoJSON 데이터가 없습니다.'}), 400

    try:
        watershed_gdf = _parse_geojson_to_gdf(geojson_str)
    except Exception as e:
        return jsonify({'status': 'error', 'message': f'GeoJSON 파싱 오류: {e}'}), 400

    analysis_id = str(uuid.uuid4())[:8]

    try:
        results, intermediate, matched_info = analyze_cn_global(watershed_gdf)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'status': 'error', 'message': str(e)}), 500

    geojson_out = _results_to_geojson(results, result_crs='EPSG:4326')
    results_clean = _clean_results_for_json(results)

    valid = [r for r in results_clean if r.get('CN') is not None]
    return jsonify({
        'status': 'ok',
        'analysis_id': analysis_id,
        'total_watersheds': len(results_clean),
        'success_count': len(valid),
        'matched_sheets': matched_info,
        'results': results_clean,
        'geojson': geojson_out,
        'report_url': None,   # Vercel에서는 파일 저장 불가 — 보고서 다운로드 미지원
        'download_url': None,
    })
