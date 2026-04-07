"""
GBMS - Profitability Routes
글로벌사업처 해외사업관리시스템 - 수익성분석 API
"""
from flask import Blueprint, request, jsonify
from datetime import datetime
try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None
import re
from models import db, ProfitabilityData, ActivityLog
from routes.auth import token_required, admin_required

profitability_bp = Blueprint('profitability', __name__)


def parse_html_report(html_content):
    """SAP HTML 리포트 파싱 (최종 버전 - span 기반)"""
    soup = BeautifulSoup(html_content, 'html.parser')
    projects = []

    # 숫자 문자열을 정수로 변환
    def to_number(text):
        if not text:
            return 0
        # 공백, 쉼표, &nbsp; 제거
        text = str(text).strip()
        text = text.replace(',', '').replace('\xa0', '').replace(' ', '').replace('\u3000', '')

        # 음수 처리 (끝에 - 붙는 경우)
        is_negative = False
        if text.endswith('-'):
            is_negative = True
            text = text[:-1]

        try:
            num = int(text) if text else 0
            return -num if is_negative else num
        except ValueError:
            return 0

    # WBS 코드 패턴
    wbs_pattern = re.compile(r'(\d{5}-\d{3}-\d{2}-\d{4})')

    # 모든 span 요소 찾기
    spans = soup.find_all('span', style='white-space:nowrap')
    print(f"[파싱 시작] 총 {len(spans)}개 span 발견")

    current_category = None

    for span in spans:
        span_text = span.get_text()

        # 프로젝트 정의 찾기 (사업구분)
        imgs = span.find_all('img')
        if imgs and imgs[0].get('src') == 's_psprde.gif':
            if '국제협력' in span_text:
                current_category = '국제협력'
            elif '해외기술용역' in span_text or '해외용역' in span_text:
                current_category = '해외기술용역'
            elif '메탄감축' in span_text or '메탄' in span_text:
                current_category = '메탄감축'
            elif '해외농업개발지원' in span_text:
                current_category = '해외농업개발지원'
            continue

        # WBS 요소 찾기 (프로젝트 데이터)
        if imgs and imgs[0].get('src') == 's_pswbel.gif' and current_category:
            wbs_match = wbs_pattern.search(span_text)
            if wbs_match:
                wbs_code = wbs_match.group(1)

                # 프로젝트명 추출 (WBS 코드 앞부분)
                project_name = span_text[:wbs_match.start()].strip()
                # 트리 문자 제거
                project_name = project_name.replace('|', '').replace('--', '').strip()

                # WBS 코드 이후의 숫자 추출
                after_wbs = span_text[wbs_match.end():].strip()

                # 공백으로 구분된 숫자들 추출
                numbers = []
                # 2개 이상의 공백 또는 탭으로 분리
                parts = re.split(r'\s{2,}|\t', after_wbs)

                for part in parts:
                    part = part.strip()
                    if not part:
                        continue

                    # 숫자 패턴 찾기 (쉼표 포함, 음수 기호 포함)
                    num_matches = re.findall(r'[\d,]+\-?', part)
                    for num_str in num_matches:
                        num = to_number(num_str)
                        numbers.append(num)

                # 최소 7개 숫자 필요: 수익, 직접비, 인건비, 경비, 합계, 사업손익, 가득수익
                if len(numbers) >= 7:
                    try:
                        revenue = numbers[0]
                        direct_cost = numbers[1]
                        labor_cost = numbers[2]
                        expense = numbers[3]
                        total_cost = numbers[4]
                        profit = numbers[5]
                        earned_revenue = numbers[6]

                        # 유효성 검사
                        if abs(revenue) > 0 or abs(total_cost) > 0:
                            projects.append({
                                'category': current_category,
                                'project_name': project_name or f'프로젝트_{wbs_code}',
                                'wbs_code': wbs_code,
                                'revenue': revenue,
                                'direct_cost': direct_cost,
                                'labor_cost': labor_cost,
                                'expense': expense,
                                'total_cost': total_cost,
                                'profit': profit,
                                'earned_revenue': earned_revenue
                            })
                    except (IndexError, ValueError) as e:
                        print(f"[파싱 오류] {project_name[:30]}, WBS={wbs_code}, 숫자={len(numbers)}개, 오류={e}")

    print(f"[파싱 완료] 총 {len(projects)}개 프로젝트 추출")
    return projects


@profitability_bp.route('/years', methods=['GET'])
@token_required
def get_years(current_user):
    """수익성분석 데이터가 있는 년도 목록"""
    try:
        years = db.session.query(ProfitabilityData.year).distinct().order_by(
            ProfitabilityData.year.desc()
        ).all()

        year_list = [y[0] for y in years if y[0]]

        if not year_list:
            # 기본값으로 2025년 추가
            year_list = [2025]

        return jsonify({
            'success': True,
            'years': year_list
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@profitability_bp.route('', methods=['GET'])
@token_required
def get_profitability(current_user):
    """수익성분석 데이터 조회"""
    try:
        year = request.args.get('year', type=int)
        category = request.args.get('category')

        query = ProfitabilityData.query

        if year:
            query = query.filter(ProfitabilityData.year == year)

        if category:
            query = query.filter(ProfitabilityData.category == category)

        records = query.order_by(
            ProfitabilityData.category,
            ProfitabilityData.project_name
        ).all()

        return jsonify({
            'success': True,
            'data': [r.to_dict() for r in records],
            'total': len(records)
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@profitability_bp.route('/stats', methods=['GET'])
@token_required
def get_stats(current_user):
    """통계 데이터 조회"""
    try:
        year = request.args.get('year', type=int)
        category = request.args.get('category')

        query = ProfitabilityData.query

        if year:
            query = query.filter(ProfitabilityData.year == year)

        if category:
            query = query.filter(ProfitabilityData.category == category)

        records = query.all()

        # 통계 계산
        total_revenue = sum(int(r.revenue or 0) for r in records)
        total_cost = sum(int(r.total_cost or 0) for r in records)
        total_profit = total_revenue - total_cost
        profit_rate = round(total_profit / total_revenue * 100, 1) if total_revenue > 0 else 0

        # 카테고리별 데이터
        by_category = {}
        for record in records:
            cat = record.category
            if cat not in by_category:
                by_category[cat] = {
                    'category': cat,
                    'revenue': 0,
                    'directCost': 0,
                    'laborCost': 0,
                    'expense': 0,
                    'totalCost': 0,
                    'profit': 0
                }
            by_category[cat]['revenue'] += int(record.revenue or 0)
            by_category[cat]['directCost'] += int(record.direct_cost or 0)
            by_category[cat]['laborCost'] += int(record.labor_cost or 0)
            by_category[cat]['expense'] += int(record.expense or 0)
            by_category[cat]['totalCost'] += int(record.total_cost or 0)
            by_category[cat]['profit'] += int(record.profit or 0)

        return jsonify({
            'success': True,
            'summary': {
                'totalRevenue': total_revenue,
                'totalCost': total_cost,
                'totalProfit': total_profit,
                'profitRate': profit_rate
            },
            'byCategory': list(by_category.values())
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@profitability_bp.route('/parse-preview', methods=['POST'])
@token_required
def parse_preview(current_user):
    """HTML 파싱 미리보기"""
    try:
        # 관리자 권한 확인
        if current_user.role != 'admin':
            return jsonify({
                'success': False,
                'error': '관리자만 접근 가능합니다.'
            }), 403

        data = request.get_json()
        html_content = data.get('htmlContent', '')

        if not html_content.strip():
            return jsonify({
                'success': False,
                'error': 'HTML 콘텐츠가 없습니다.'
            }), 400

        projects = parse_html_report(html_content)

        # 카테고리별 분류
        summary = {}
        for project in projects:
            cat = project['category']
            summary[cat] = summary.get(cat, 0) + 1

        return jsonify({
            'success': True,
            'total': len(projects),
            'summary': summary,
            'projects': projects[:20]  # 처음 20개만 반환
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@profitability_bp.route('/batch', methods=['POST'])
@token_required
def batch_import(current_user):
    """데이터 일괄 저장"""
    try:
        # 관리자 권한 확인
        if current_user.role != 'admin':
            print(f"[권한 오류] 사용자 {current_user.username}은 관리자가 아닙니다.")
            return jsonify({
                'success': False,
                'error': '관리자만 접근 가능합니다.'
            }), 403

        data = request.get_json()
        year = data.get('year')
        month_from = data.get('monthFrom', 1)
        month_to = data.get('monthTo', 12)
        html_content = data.get('htmlContent', '')
        overwrite = data.get('overwrite', True)

        print(f"[저장 요청] year={year}, monthFrom={month_from}, monthTo={month_to}, contentLength={len(html_content)}, overwrite={overwrite}")

        if not year or not html_content:
            print("[입력 오류] 연도 또는 HTML 데이터가 없습니다.")
            return jsonify({
                'success': False,
                'error': '연도와 HTML 데이터는 필수입니다.'
            }), 400

        # 기존 데이터 삭제 (overwrite=True인 경우)
        deleted_count = 0
        if overwrite:
            deleted_count = ProfitabilityData.query.filter(
                ProfitabilityData.year == year
            ).delete()
            print(f"[기존 데이터 삭제] {deleted_count}개 레코드 삭제됨")

        # 새 데이터 파싱 및 저장
        print("[파싱 시작]")
        projects = parse_html_report(html_content)
        print(f"[파싱 완료] {len(projects)}개 프로젝트 추출")

        if len(projects) == 0:
            print("[파싱 실패] 추출된 프로젝트가 없습니다.")
            return jsonify({
                'success': False,
                'error': 'HTML에서 프로젝트 데이터를 추출할 수 없습니다. 파일 형식을 확인해주세요.'
            }), 400

        saved_count = 0
        failed_count = 0

        for i, project in enumerate(projects):
            try:
                record = ProfitabilityData(
                    year=year,
                    month_from=month_from,
                    month_to=month_to,
                    category=project['category'],
                    project_name=project['project_name'],
                    wbs_code=project['wbs_code'],
                    revenue=project['revenue'],
                    direct_cost=project['direct_cost'],
                    labor_cost=project['labor_cost'],
                    expense=project['expense'],
                    total_cost=project['total_cost'],
                    profit=project['profit'],
                    earned_revenue=project['earned_revenue'],
                    created_by=current_user.id
                )
                db.session.add(record)
                saved_count += 1
            except Exception as e:
                failed_count += 1
                print(f"[저장 오류 {i+1}] {project.get('project_name', 'Unknown')[:30]}, 오류: {str(e)}")
                continue

        # Activity Log 기록
        log = ActivityLog(
            user_id=current_user.id,
            action='import',
            entity_type='profitability',
            entity_id=year,
            description=f'{year}년 수익성분석 데이터 {saved_count}개 입력',
            ip_address=request.remote_addr
        )
        db.session.add(log)

        print(f"[커밋 시작] {saved_count}개 레코드, 실패: {failed_count}개")
        db.session.commit()
        print("[커밋 완료]")

        return jsonify({
            'success': True,
            'message': f'{saved_count}개 프로젝트 데이터가 저장되었습니다.',
            'savedCount': saved_count,
            'failedCount': failed_count,
            'deletedCount': deleted_count
        })
    except Exception as e:
        print(f"[전체 오류] {str(e)}")
        import traceback
        traceback.print_exc()
        db.session.rollback()
        return jsonify({
            'success': False,
            'error': f'저장 중 오류 발생: {str(e)}'
        }), 500
