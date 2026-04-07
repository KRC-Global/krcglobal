"""
GBMS - Documents Routes
글로벌사업처 해외사업관리시스템 - 문서관리 API
"""
import os
from flask import Blueprint, request, jsonify, send_file, current_app
from datetime import datetime
from werkzeug.utils import secure_filename
from models import db, Document, ActivityLog
from routes.auth import token_required

documents_bp = Blueprint('documents', __name__)


def allowed_file(filename):
    """Check if file extension is allowed"""
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in current_app.config['ALLOWED_EXTENSIONS']


@documents_bp.route('', methods=['GET'])
@token_required
def get_documents(current_user):
    """Get all documents with filters"""
    project_id = request.args.get('project_id', type=int)
    doc_type = request.args.get('type')
    department = request.args.get('department')
    search = request.args.get('search')
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    
    query = Document.query
    
    if project_id:
        query = query.filter(Document.project_id == project_id)
    
    if doc_type:
        query = query.filter(Document.doc_type == doc_type)
    
    if department:
        query = query.filter(Document.department == department)
    
    if search:
        query = query.filter(
            db.or_(
                Document.title.ilike(f'%{search}%'),
                Document.file_name.ilike(f'%{search}%')
            )
        )
    
    query = query.order_by(Document.created_at.desc())
    
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    
    return jsonify({
        'success': True,
        'data': [d.to_dict() for d in pagination.items],
        'total': pagination.total,
        'pages': pagination.pages,
        'currentPage': page
    })


@documents_bp.route('/<int:doc_id>', methods=['GET'])
@token_required
def get_document(current_user, doc_id):
    """Get single document by ID"""
    document = Document.query.get_or_404(doc_id)
    
    return jsonify({
        'success': True,
        'data': document.to_dict()
    })


@documents_bp.route('/upload', methods=['POST'])
@token_required
def upload_document(current_user):
    """Upload document"""
    if 'file' not in request.files:
        return jsonify({'success': False, 'message': '파일이 없습니다.'}), 400
    
    file = request.files['file']
    
    if file.filename == '':
        return jsonify({'success': False, 'message': '파일이 선택되지 않았습니다.'}), 400
    
    if not allowed_file(file.filename):
        return jsonify({'success': False, 'message': '허용되지 않는 파일 형식입니다.'}), 400
    
    # Get metadata from form
    title = request.form.get('title', file.filename)
    doc_type = request.form.get('docType', 'other')
    project_id = request.form.get('projectId', type=int)
    description = request.form.get('description')
    department = request.form.get('department', current_user.department)
    
    # Secure filename and save
    filename = secure_filename(file.filename)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    saved_filename = f"{timestamp}_{filename}"
    
    # Create upload directory if not exists
    project_dir = str(project_id) if project_id else 'general'
    upload_path = os.path.join(current_app.config['UPLOAD_FOLDER'], project_dir)
    os.makedirs(upload_path, exist_ok=True)

    file_path = os.path.join(upload_path, saved_filename)
    file.save(file_path)

    # Get file info
    file_size = os.path.getsize(file_path)
    file_ext = filename.rsplit('.', 1)[1].lower() if '.' in filename else ''

    # Store relative path for platform independence: {project_id}/{filename}
    relative_path = os.path.join(project_dir, saved_filename)

    # Create document record
    document = Document(
        project_id=project_id,
        title=title,
        doc_type=doc_type,
        file_name=filename,
        file_path=relative_path,  # 상대 경로 저장 (플랫폼 독립적)
        file_size=file_size,
        file_type=file_ext,
        description=description,
        department=department,
        created_by=current_user.id
    )
    
    db.session.add(document)
    
    # Log activity
    log = ActivityLog(
        user_id=current_user.id,
        action='create',
        entity_type='document',
        entity_id=document.id,
        description=f'문서 업로드: {title}',
        ip_address=request.remote_addr
    )
    db.session.add(log)
    
    db.session.commit()
    
    return jsonify({
        'success': True,
        'message': '문서가 업로드되었습니다.',
        'data': document.to_dict()
    }), 201


@documents_bp.route('/<int:doc_id>/download', methods=['GET'])
@token_required
def download_document(current_user, doc_id):
    """Download document"""
    document = Document.query.get_or_404(doc_id)

    if not document.file_path:
        return jsonify({'success': False, 'message': '파일 경로가 없습니다.'}), 404

    # 파일 경로 생성 (상대 경로가 저장되어 있으므로 UPLOAD_FOLDER와 결합)
    file_path = os.path.join(current_app.config['UPLOAD_FOLDER'], document.file_path)

    if not os.path.exists(file_path):
        return jsonify({'success': False, 'message': '파일을 찾을 수 없습니다.'}), 404

    return send_file(
        file_path,
        as_attachment=True,
        download_name=document.file_name
    )


@documents_bp.route('/<int:doc_id>', methods=['PUT'])
@token_required
def update_document(current_user, doc_id):
    """Update document metadata"""
    document = Document.query.get_or_404(doc_id)
    data = request.get_json()
    
    if 'title' in data:
        document.title = data['title']
    if 'docType' in data:
        document.doc_type = data['docType']
    if 'description' in data:
        document.description = data['description']
    if 'version' in data:
        document.version = data['version']
    if 'isPublic' in data:
        document.is_public = data['isPublic']
    
    db.session.commit()
    
    return jsonify({
        'success': True,
        'message': '문서 정보가 수정되었습니다.',
        'data': document.to_dict()
    })


@documents_bp.route('/<int:doc_id>', methods=['DELETE'])
@token_required
def delete_document(current_user, doc_id):
    """Delete document"""
    document = Document.query.get_or_404(doc_id)
    
    # Delete file from disk
    if document.file_path:
        file_path = os.path.join(current_app.config['UPLOAD_FOLDER'], document.file_path)
        if os.path.exists(file_path):
            os.remove(file_path)
    
    # Log activity
    log = ActivityLog(
        user_id=current_user.id,
        action='delete',
        entity_type='document',
        entity_id=document.id,
        description=f'문서 삭제: {document.title}',
        ip_address=request.remote_addr
    )
    db.session.add(log)
    
    db.session.delete(document)
    db.session.commit()
    
    return jsonify({
        'success': True,
        'message': '문서가 삭제되었습니다.'
    })
