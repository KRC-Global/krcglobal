"""
PDF 압축 엔진 (메모리 기반)
- 원본: 001. PDF압축/compress_engine.py
- 서버 저장 없이 BytesIO로 처리
- 강력한 압축 옵션 지원
"""

from io import BytesIO

try:
    import pikepdf
    from pikepdf import Pdf, PdfImage
    from PIL import Image
    HAS_PDF_LIBS = True
except ImportError:
    pikepdf = None
    Pdf = None
    PdfImage = None
    Image = None
    HAS_PDF_LIBS = False


# 압축 레벨 프리셋
COMPRESSION_PRESETS = {
    'low': {        # 최소 압축 (최고 화질)
        'quality': 85,
        'dpi': 300,
        'max_dimension': 4000
    },
    'medium': {     # 중간 압축 (권장)
        'quality': 70,
        'dpi': 200,
        'max_dimension': 2500
    },
    'high': {       # 강한 압축 (50%+ 감소 목표)
        'quality': 60,
        'dpi': 150,
        'max_dimension': 2000
    },
    'maximum': {    # 최대 압축 (화질 다소 저하)
        'quality': 45,
        'dpi': 120,
        'max_dimension': 1500
    }
}


class PDFCompressor:
    """PDF 압축 클래스 (메모리 기반)"""

    def __init__(self, quality=60, dpi_threshold=150, max_dimension=2000, preset=None):
        """
        Args:
            quality: JPEG 이미지 품질 (0-100, 기본값 60)
            dpi_threshold: 이미지 리샘플링 기준 DPI (기본값 150)
            max_dimension: 이미지 최대 픽셀 크기 (기본값 2000)
            preset: 압축 프리셋 ('low', 'medium', 'high', 'maximum')
        """
        if not HAS_PDF_LIBS:
            raise ImportError('PDF 압축 기능을 사용하려면 pikepdf, Pillow 패키지가 필요합니다.')
        if preset and preset in COMPRESSION_PRESETS:
            p = COMPRESSION_PRESETS[preset]
            self.quality = p['quality']
            self.dpi_threshold = p['dpi']
            self.max_dimension = p['max_dimension']
        else:
            self.quality = quality
            self.dpi_threshold = dpi_threshold
            self.max_dimension = max_dimension

    def compress_from_bytes(self, input_bytes: bytes) -> tuple:
        """
        바이트 스트림에서 PDF 압축

        Args:
            input_bytes: 입력 PDF 바이트

        Returns:
            tuple: (압축된 PDF 바이트, 메타정보 dict)
        """
        original_size = len(input_bytes)

        # BytesIO로 PDF 열기
        input_stream = BytesIO(input_bytes)
        pdf = Pdf.open(input_stream)

        total_pages = len(pdf.pages)

        # 각 페이지 이미지 최적화
        images_optimized = 0
        images_total = 0
        for page_num, page in enumerate(pdf.pages):
            optimized, total = self._optimize_page_images(page)
            images_optimized += optimized
            images_total += total

        # BytesIO로 저장 (강력한 압축 옵션)
        output_stream = BytesIO()
        pdf.save(
            output_stream,
            compress_streams=True,
            stream_decode_level=pikepdf.StreamDecodeLevel.all,  # 모든 스트림 디코딩
            object_stream_mode=pikepdf.ObjectStreamMode.generate,
            recompress_flate=True,
            linearize=True  # 웹 최적화 (normalize_content와 동시 사용 불가)
        )
        pdf.close()

        output_stream.seek(0)
        compressed_bytes = output_stream.read()
        compressed_size = len(compressed_bytes)

        # 압축률 계산
        if original_size > 0:
            compression_ratio = ((original_size - compressed_size) / original_size) * 100
        else:
            compression_ratio = 0

        # 압축 후 용량이 증가하면 원본 반환
        if compressed_size >= original_size:
            meta = {
                'original_size': original_size,
                'compressed_size': original_size,
                'compression_ratio': 0,
                'total_pages': total_pages,
                'images_optimized': images_optimized,
                'images_total': images_total,
                'note': '이미 최적화된 PDF입니다. 원본을 유지합니다.'
            }
            return input_bytes, meta

        meta = {
            'original_size': original_size,
            'compressed_size': compressed_size,
            'compression_ratio': compression_ratio,
            'total_pages': total_pages,
            'images_optimized': images_optimized,
            'images_total': images_total
        }

        return compressed_bytes, meta

    def _optimize_page_images(self, page):
        """페이지의 모든 이미지 최적화"""
        optimized_count = 0
        total_count = 0

        try:
            # 페이지의 리소스에서 이미지 찾기
            if '/Resources' not in page:
                return 0, 0

            if '/XObject' not in page.Resources:
                return 0, 0

            for name, obj in list(page.Resources.XObject.items()):
                if not isinstance(obj, pikepdf.Stream):
                    continue

                if obj.Subtype != '/Image':
                    continue

                total_count += 1
                try:
                    if self._optimize_image(obj):
                        optimized_count += 1
                except Exception as e:
                    # 특정 이미지 최적화 실패해도 계속 진행
                    continue

        except Exception:
            pass

        return optimized_count, total_count

    def _optimize_image(self, image_obj):
        """개별 이미지 최적화 - 강제 재압축"""
        try:
            # 원본 이미지 크기 저장
            try:
                original_data = bytes(image_obj.read_bytes())
                original_size = len(original_data)
            except:
                original_size = 0

            # PdfImage로 변환
            pdf_image = PdfImage(image_obj)

            # 이미지를 PIL Image로 변환
            pil_image = pdf_image.as_pil_image()

            # 이미지 크기 확인
            width, height = pil_image.size

            # 너무 작은 이미지는 건너뛰기 (50x50 미만)
            if width < 50 or height < 50:
                return False

            # 이미지 리사이즈 (최대 크기 제한)
            resized = False
            if width > self.max_dimension or height > self.max_dimension:
                # 비율 유지하며 축소
                ratio = min(self.max_dimension / width, self.max_dimension / height)
                new_width = int(width * ratio)
                new_height = int(height * ratio)
                pil_image = pil_image.resize(
                    (new_width, new_height),
                    Image.Resampling.LANCZOS
                )
                resized = True

            # DPI 기반 추가 리사이즈
            # A4 크기(11.7 x 16.5 인치) 기준
            max_width_at_dpi = int(self.dpi_threshold * 11.7)
            max_height_at_dpi = int(self.dpi_threshold * 16.5)

            current_width, current_height = pil_image.size
            if current_width > max_width_at_dpi or current_height > max_height_at_dpi:
                ratio = min(max_width_at_dpi / current_width, max_height_at_dpi / current_height)
                if ratio < 1:
                    new_width = int(current_width * ratio)
                    new_height = int(current_height * ratio)
                    pil_image = pil_image.resize(
                        (new_width, new_height),
                        Image.Resampling.LANCZOS
                    )
                    resized = True

            # RGBA 이미지는 RGB로 변환
            if pil_image.mode in ('RGBA', 'LA', 'P'):
                rgb_image = Image.new('RGB', pil_image.size, (255, 255, 255))
                if pil_image.mode == 'P':
                    pil_image = pil_image.convert('RGBA')
                if pil_image.mode in ('RGBA', 'LA'):
                    rgb_image.paste(pil_image, mask=pil_image.split()[-1])
                else:
                    rgb_image.paste(pil_image)
                pil_image = rgb_image
            elif pil_image.mode != 'RGB':
                pil_image = pil_image.convert('RGB')

            # JPEG로 압축
            img_byte_arr = BytesIO()
            pil_image.save(
                img_byte_arr,
                format='JPEG',
                quality=self.quality,
                optimize=True,
                progressive=True  # 프로그레시브 JPEG
            )
            img_byte_arr.seek(0)
            compressed_data = img_byte_arr.read()
            compressed_size = len(compressed_data)

            # 리사이즈 했거나, 압축 효과가 있으면 적용
            if resized or compressed_size < original_size:
                # PDF 이미지 객체 업데이트
                image_obj.write(compressed_data, filter=pikepdf.Name.DCTDecode)
                image_obj.ColorSpace = pikepdf.Name.DeviceRGB

                # 이미지 크기 메타데이터 업데이트
                final_width, final_height = pil_image.size
                image_obj.Width = final_width
                image_obj.Height = final_height

                return True

            return False

        except Exception:
            return False


def format_size(size_bytes: int) -> str:
    """바이트를 읽기 쉬운 형식으로 변환"""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024.0:
            return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.2f} TB"
