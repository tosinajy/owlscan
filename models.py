# models.py

from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import Text
from sqlalchemy.dialects.mysql import LONGTEXT

db = SQLAlchemy()

class Setting(db.Model):
    __tablename__ = 'settings'
    setting_key = db.Column(db.String(50), primary_key=True)
    setting_value = db.Column(db.String(255), nullable=False)

class Scan(db.Model):
    __tablename__ = 'scans'
    id = db.Column(db.Integer, primary_key=True)
    start_url = db.Column(db.String(2083), nullable=False)
    status = db.Column(db.Enum('pending', 'crawling', 'crawled', 'analyzing', 'completed', 'failed'), nullable=False, default='pending')
    created_at = db.Column(db.TIMESTAMP, server_default=db.func.now())
    total_issues = db.Column(db.Integer, default=0)
    new_urls_count = db.Column(db.Integer, default=0)
    updated_urls_count = db.Column(db.Integer, default=0)
    existing_urls_count = db.Column(db.Integer, default=0)
    analysis_json = db.Column(Text, nullable=True)
    
    pages = db.relationship('Page', backref='scan', lazy=True, cascade="all, delete-orphan")
    links = db.relationship('Link', backref='scan', lazy=True, cascade="all, delete-orphan")
    images = db.relationship('Image', backref='scan', lazy=True, cascade="all, delete-orphan")

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
    crawl_status = db.Column(db.Enum('new', 'updated', 'existing'), default='new')
    html_content = db.Column(LONGTEXT, nullable=True)

    # Advanced Analysis Metrics
    word_count = db.Column(db.Integer, default=0)
    reading_time_min = db.Column(db.Float, default=0.0)
    flesch_score = db.Column(db.Float, default=0.0)
    h1_count = db.Column(db.Integer, default=0)
    internal_links_count = db.Column(db.Integer, default=0)
    external_links_count = db.Column(db.Integer, default=0)
    top_keywords = db.Column(db.Text, nullable=True)

    # NEW: Spelling & Grammar
    spelling_issues_count = db.Column(db.Integer, default=0)
    grammar_issues_count = db.Column(db.Integer, default=0)
    spelling_examples = db.Column(db.Text, nullable=True)
    grammar_error_context = db.Column(db.Text, nullable=True) # NEW: To store JSON list of grammar snippets

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