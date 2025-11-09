# app.py

from flask import (
    Flask, render_template, request, jsonify, redirect, url_for, Response, flash
)
from threading import Thread
from sqlalchemy import func, desc
import json

# --- Local Imports ---
from config import Config
from models import db, Scan, Page, Setting, Link, Image
from crawler import run_crawler
from helpers import analyze_results, generate_csv

app = Flask(__name__)
app.config.from_object(Config)
db.init_app(app)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/start_scan', methods=['POST'])
def start_scan():
    start_url = request.form.get('url')
    if not start_url: return jsonify({'error': 'URL is required'}), 400
    new_scan = Scan(start_url=start_url, status='pending')
    db.session.add(new_scan)
    db.session.commit()
    Thread(target=run_crawler, args=(app, db, new_scan.id), daemon=True).start()
    return jsonify({'scan_id': new_scan.id})

@app.route('/scan/<int:scan_id>')
def view_results(scan_id):
    """Main view designed to show the most relevant stage (Analysis if complete, Data if just crawled)."""
    scan = db.session.get(Scan, scan_id)
    if not scan: return "Scan not found", 404

    if scan.status == 'crawled':
         return redirect(url_for('view_scan_data', scan_id=scan_id))
    elif scan.status == 'completed':
        settings = {s.setting_key: s.setting_value for s in Setting.query.all()}
        analysis = json.loads(scan.analysis_json) if scan.analysis_json else analyze_results(Page.query.filter_by(scan_id=scan.id).all(), settings)
        return render_template('results.html', scan=scan, analysis=analysis, settings=settings)
    else:
        return render_template('results.html', scan=scan, analysis=None, settings={})

@app.route('/scan_data/<int:scan_id>')
def view_scan_data(scan_id):
    """Explicitly view the intermediary raw data, even if analysis is complete."""
    scan = db.session.get(Scan, scan_id)
    if not scan: return "Scan not found", 404
    
    pages = Page.query.filter_by(scan_id=scan.id).order_by(Page.url).all()
    return render_template('intermediary_results.html', scan=scan, pages=pages)

@app.route('/analyze/<int:scan_id>', methods=['POST'])
def perform_analysis(scan_id):
    scan = db.session.get(Scan, scan_id)
    if not scan or scan.status != 'crawled': return jsonify({'error': 'Invalid scan state'}), 400

    scan.status = 'analyzing'
    db.session.commit()

    try:
        settings = {s.setting_key: s.setting_value for s in Setting.query.all()}
        pages = Page.query.filter_by(scan_id=scan.id).all()
        analysis = analyze_results(pages, settings)
        
        analysis['rate_limit_errors'] = [{'source_url': l.source_url, 'target_url': l.target_url, 'anchor_text': l.anchor_text, 'status_code': l.status_code} for l in Link.query.filter_by(scan_id=scan.id, status_code=429).all()]
        analysis['broken_links'] = [{'source_url': l.source_url, 'target_url': l.target_url, 'anchor_text': l.anchor_text, 'status_code': l.status_code} for l in Link.query.filter(Link.scan_id == scan.id, Link.is_broken == True, Link.status_code != 429).all()]
        analysis['large_images'] = [{'image_url': i.image_url, 'page_url': i.page_url, 'file_size_kb': i.file_size_kb} for i in Image.query.filter_by(scan_id=scan.id, is_large=True).all()]
        analysis['missing_alt_images'] = [{'image_url': i.image_url, 'page_url': i.page_url} for i in Image.query.filter_by(scan_id=scan.id, missing_alt=True).all()]

        for key in ['missing_titles', 'short_titles', 'long_titles', 'missing_descriptions', 'short_descriptions', 'long_descriptions', 'orphaned_pages']:
             analysis[key] = [{'url': p.url, 'title': p.title, 'meta_description': p.meta_description} for p in analysis[key]]
        for key in ['duplicate_titles', 'duplicate_descriptions', 'duplicate_content']:
            analysis[key] = {k: [{'url': p.url} for p in v] for k, v in analysis[key].items()}

        scan.total_issues = sum([len(analysis[k]) for k in ['broken_links', 'large_images', 'missing_alt_images', 'missing_titles', 'missing_descriptions', 'orphaned_pages']])
        scan.analysis_json = json.dumps(analysis)
        scan.status = 'completed'
        db.session.commit()
        return jsonify({'status': 'success'})
    except Exception as e:
        scan.status = 'failed'
        db.session.commit()
        return jsonify({'error': str(e)}), 500

@app.route('/scan_status/<int:scan_id>')
def scan_status(scan_id):
    scan = db.session.get(Scan, scan_id)
    return jsonify({'status': scan.status if scan else 'not_found'})

@app.route('/history')
def history():
    page = request.args.get('page', 1, type=int)
    per_page = 10
    subq = db.session.query(Scan.start_url, func.max(Scan.created_at).label('max_created_at'), func.count(Scan.id).label('scan_count')).group_by(Scan.start_url).subquery()
    query = db.session.query(Scan, subq.c.scan_count).join(subq, (Scan.start_url == subq.c.start_url) & (Scan.created_at == subq.c.max_created_at)).order_by(desc(Scan.created_at))
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    return render_template('history.html', pagination=pagination)

@app.route('/url_history')
def url_history():
    url = request.args.get('url')
    if not url: return redirect(url_for('history'))
    scans = Scan.query.filter_by(start_url=url).order_by(Scan.created_at.desc()).all()
    return render_template('url_history.html', start_url=url, scans=scans)

@app.route('/settings', methods=['GET', 'POST'])
def settings():
    if request.method == 'POST':
        for key, value in request.form.items():
            setting = Setting.query.get(key)
            if setting: setting.setting_value = value
        db.session.commit()
        flash('Settings updated successfully!', 'success')
        return redirect(url_for('settings'))
    settings_db = Setting.query.all()
    settings = {s.setting_key: s.setting_value for s in settings_db}
    return render_template('settings.html', settings=settings)

@app.route('/export/csv/<int:scan_id>')
def export_csv(scan_id):
    pages = Page.query.filter_by(scan_id=scan_id).all()
    return Response(generate_csv(pages), mimetype="text/csv", headers={"Content-disposition": f"attachment; filename=scan_{scan_id}_export.csv"})

@app.route('/export/json/<int:scan_id>')
def export_json(scan_id):
    pages = Page.query.filter_by(scan_id=scan_id).all()
    json_data = json.dumps([{'url': p.url, 'status_code': p.status_code, 'title': p.title, 'meta_description': p.meta_description, 'is_orphan': p.is_orphan, 'incoming_links': p.incoming_links} for p in pages], indent=4)
    return Response(json_data, mimetype="application/json", headers={"Content-disposition": f"attachment; filename=scan_{scan_id}_export.json"})

def setup_database(app_context):
    with app_context:
        db.create_all()
        if not Setting.query.first():
            db.session.bulk_save_objects([Setting(setting_key='min_title_length', setting_value='10'), Setting(setting_key='max_title_length', setting_value='60'), Setting(setting_key='min_desc_length', setting_value='70'), Setting(setting_key='max_desc_length', setting_value='160'), Setting(setting_key='max_image_size_kb', setting_value='150'), Setting(setting_key='max_pages_limit', setting_value='200')])
            db.session.commit()

if __name__ == '__main__':
    setup_database(app.app_context())
    app.run(debug=True)