# models.py

from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

class Setting(db.Model):
    __tablename__ = 'settings'
    setting_key = db.Column(db.String(50), primary_key=True)
    setting_value = db.Column(db.String(255), nullable=False)

class Scan(db.Model):
    __tablename__ = 'scans'
    id = db.Column(db.Integer, primary_key=True)
    start_url = db.Column(db.String(2083), nullable=False)
    status = db.Column(db.Enum('pending', 'running', 'completed', 'failed'), nullable=False, default='pending')
    created_at = db.Column(db.TIMESTAMP, server_default=db.func.now())
    # NEW COLUMN:
    total_issues = db.Column(db.Integer, default=0)
    
    pages = db.relationship('Page', backref='scan', lazy=True, cascade="all, delete-orphan")
    links = db.relationship('Link', backref='scan', lazy=True, cascade="all, delete-orphan")
    images = db.relationship('Image', backref='scan', lazy=True, cascade="all, delete-orphan")

# ... (Keep Page, Link, and Image models exactly as they were in the previous step) ...
class Page(db.Model):
    __tablename__ = 'pages'
    id = db.Column(db.Integer, primary_key=True)
    scan_id = db.Column(db.Integer, db.ForeignKey('scans.id'), nullable=False)
    url = db.Column(db.String(2083), nullable=False)
    status_code = db.Column(db.Integer)
    title = db.Column(db.Text)
    meta_description = db.Column(db.Text)
    content_hash = db.Column(db.String(64))
    is_orphan = db.Column(db.Boolean, default=False)
    incoming_links = db.Column(db.Integer, default=0)

class Link(db.Model):
    __tablename__ = 'links'
    id = db.Column(db.Integer, primary_key=True)
    scan_id = db.Column(db.Integer, db.ForeignKey('scans.id'), nullable=False)
    source_url = db.Column(db.String(2083), nullable=False)
    target_url = db.Column(db.String(2083), nullable=False)
    anchor_text = db.Column(db.Text)
    status_code = db.Column(db.Integer)
    is_broken = db.Column(db.Boolean, default=False)

class Image(db.Model):
    __tablename__ = 'images'
    id = db.Column(db.Integer, primary_key=True)
    scan_id = db.Column(db.Integer, db.ForeignKey('scans.id'), nullable=False)
    page_url = db.Column(db.String(2083), nullable=False)
    image_url = db.Column(db.String(2083), nullable=False)
    alt_text = db.Column(db.Text)
    file_size_kb = db.Column(db.Integer)
    is_large = db.Column(db.Boolean, default=False)
    missing_alt = db.Column(db.Boolean, default=False)