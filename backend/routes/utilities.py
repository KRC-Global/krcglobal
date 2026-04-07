"""
편의기능 API Blueprint
- PDF 압축 (메모리 기반 처리, 서버 저장 없음)
"""

from flask import Blueprint, request, jsonify, send_file
from io import BytesIO
from werkzeug.utils import secure_filename
from routes.auth import token_required
from utils.pdf_compressor import PDFCompressor

utilities_bp = Blueprint('utilities', __name__)

# 허용 확장자
ALLOWED_PDF = {'pdf'}

# 최대 파일 크기 (500MB)
MAX_FILE_SIZE = 500 * 1024 * 1024


def allowed_file(filename, allowed_set):
    """파일 확장자 확인"""
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in allowed_set


@utilities_bp.route('/compress-pdf', methods=['POST'])
@token_required
def compress_pdf(current_user):
    """
    PDF 압축 API - 메모리 기반 처리

    Request:
        - file: PDF 파일 (multipart/form-data)
        - level: 압축 레벨 ('low', 'medium', 'high', 'maximum') 기본값 'high'
        - quality: 이미지 품질 1-100 (level 미지정 시 사용, 기본 60)
        - dpi_threshold: DPI 임계값 (level 미지정 시 사용, 기본 150)

    Response:
        - 성공: 압축된 PDF 파일 다운로드
        - 실패: JSON 에러 메시지
    """
    # 파일 존재 확인
    if 'file' not in request.files:
        return jsonify({'success': False, 'message': '파일이 없습니다.'}), 400

    file = request.files['file']

    # 파일 선택 확인
    if file.filename == '':
        return jsonify({'success': False, 'message': '파일이 선택되지 않았습니다.'}), 400

    # PDF 확장자 확인
    if not allowed_file(file.filename, ALLOWED_PDF):
        return jsonify({'success': False, 'message': 'PDF 파일만 지원합니다.'}), 400

    # 파일 크기 체크
    file.seek(0, 2)
    file_size = file.tell()
    file.seek(0)

    if file_size > MAX_FILE_SIZE:
        return jsonify({
            'success': False,
            'message': '파일 크기가 500MB를 초과합니다.'
        }), 400

    if file_size == 0:
        return jsonify({
            'success': False,
            'message': '빈 파일입니다.'
        }), 400

    try:
        # 압축 레벨 프리셋 (기본값: high - 50%+ 압축 목표)
        level = request.form.get('level', 'high')

        # 유효한 레벨인지 확인
        valid_levels = ['low', 'medium', 'high', 'maximum']
        if level not in valid_levels:
            level = 'high'

        # 파일 바이트 읽기
        input_bytes = file.read()

        # PDF 압축 실행 (프리셋 사용)
        compressor = PDFCompressor(preset=level)
        compressed_bytes, meta = compressor.compress_from_bytes(input_bytes)

        # 파일명 생성
        original_name = secure_filename(file.filename)
        if original_name:
            base_name = original_name.rsplit('.', 1)[0]
        else:
            base_name = 'document'
        output_name = f"{base_name}_compressed.pdf"

        # BytesIO로 반환
        output = BytesIO(compressed_bytes)

        response = send_file(
            output,
            mimetype='application/pdf',
            as_attachment=True,
            download_name=output_name
        )

        # 메타정보를 헤더에 추가 (프론트엔드에서 결과 표시용)
        response.headers['X-Original-Size'] = str(meta['original_size'])
        response.headers['X-Compressed-Size'] = str(meta['compressed_size'])
        response.headers['X-Compression-Ratio'] = f"{meta['compression_ratio']:.1f}"
        response.headers['X-Total-Pages'] = str(meta['total_pages'])
        response.headers['X-Images-Optimized'] = str(meta.get('images_optimized', 0))
        response.headers['X-Images-Total'] = str(meta.get('images_total', 0))
        response.headers['X-Compression-Level'] = level
        if meta.get('note'):
            response.headers['X-Note'] = meta['note']

        # CORS를 위한 헤더 노출 설정
        response.headers['Access-Control-Expose-Headers'] = \
            'X-Original-Size, X-Compressed-Size, X-Compression-Ratio, X-Total-Pages, X-Images-Optimized, X-Images-Total, X-Compression-Level, X-Note'

        return response

    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'압축 중 오류가 발생했습니다: {str(e)}'
        }), 500


@utilities_bp.route('/supported-formats', methods=['GET'])
def get_supported_formats():
    """
    지원 포맷 목록 반환
    """
    return jsonify({
        'success': True,
        'data': {
            'compress': ['.pdf'],
            'notes': {
                '.pdf': 'PDF 파일 압축 (이미지 최적화, 최대 500MB)'
            }
        }
    })
