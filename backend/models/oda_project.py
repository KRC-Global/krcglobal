"""
ODA Projects Model
ODA 사업 전용 테이블
"""
from models import db
from datetime import datetime


class OdaProject(db.Model):
    """ODA 사업 모델"""
    __tablename__ = 'oda_projects'
    
    id = db.Column(db.Integer, primary_key=True)
    number = db.Column(db.Integer, index=True)  # 번호
    
    country = db.Column(db.String(100), nullable=False, index=True)  # 국가
    latitude = db.Column(db.Numeric(10, 7))  # 위도
    longitude = db.Column(db.Numeric(10, 7))  # 경도
    
    title = db.Column(db.String(500), nullable=False)  # 사업명
    description = db.Column(db.Text)  # 사업 설명
    
    period = db.Column(db.String(50))  # 사업기간 (예: '20-'25)
    budget = db.Column(db.Numeric(15, 2))  # 예산(백만원)
    
    project_type = db.Column(db.String(100))  # 사업형태 (양자무상, 다자성양자 등)
    status = db.Column(db.String(50))  # 진행상태
    continent = db.Column(db.String(50))  # 대륙
    
    # 메타 정보
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    
    creator = db.relationship('User', foreign_keys=[created_by])
    
    def to_dict(self):
        return {
            'id': self.id,
            'number': self.number,
            'country': self.country,
            'latitude': float(self.latitude) if self.latitude else None,
            'longitude': float(self.longitude) if self.longitude else None,
            'title': self.title,
            'description': self.description,
            'period': self.period,
            'budget': float(self.budget) if self.budget else 0,
            'projectType': self.project_type,
            'status': self.status,
            'continent': self.continent,
            'createdAt': self.created_at.isoformat() if self.created_at else None,
            'updatedAt': self.updated_at.isoformat() if self.updated_at else None,
            'createdBy': self.creator.name if self.creator else None
        }
