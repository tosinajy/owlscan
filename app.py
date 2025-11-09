# app.py

from flask import (
    Flask, render_template, request, jsonify, redirect, url_for, Response, flash
)
from sqlalchemy import func
from threading import Thread
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
    if not start_url:
        return jsonify({'error': 'URL is required'}), 400

    new_scan = Scan(start_url=start_url, status='pending')
    db.session.add(new_scan)
    db.session.commit()

    scan_thread = Thread(target=run_crawler, args=(app, db, new_scan.id))
    scan_thread.daemon = True
    scan_thread.start()

    return jsonify({'scan_id': new_scan.id})

@app.route('/scan/<int:scan_id>')
def view_results(scan_id):
    scan = db.session.get(Scan, scan_id)
    if not scan:
        return "Scan not found", 404

    # CORRECT: Query for settings and define the variable outside the 'if' block.
    settings_db = Setting.query.all()
    settings = {s.setting_key: s.setting_value for s in settings_db}
        
    analysis = None
    if scan.status == 'completed':
        pages = Page.query.filter_by(scan_id=scan.id).order_by(Page.url).all()
        
        # Run the main analysis helper
        analysis = analyze_results(pages, settings)
        
        # Add new, detailed queries to the analysis dictionary
        analysis['broken_links'] = Link.query.filter_by(scan_id=scan.id, is_broken=True).all()
        analysis['large_images'] = Image.query.filter_by(scan_id=scan.id, is_large=True).all()
        analysis['missing_alt_images'] = Image.query.filter_by(scan_id=scan.id, missing_alt=True).all()

    # The 'settings' variable is now always available here.
    return render_template('results.html', scan=scan, analysis=analysis, settings=settings)

@app.route('/scan_status/<int:scan_id>')
def scan_status(scan_id):
    scan = db.session.get(Scan, scan_id)
    return jsonify({'status': scan.status if scan else 'not_found'})

@app.route('/settings', methods=['GET', 'POST'])
def settings():
    if request.method == 'POST':
        for key, value in request.form.items():
            setting = Setting.query.get(key)
            if setting:
                setting.setting_value = value
        db.session.commit()
        flash('Settings updated successfully!', 'success')
        return redirect(url_for('settings'))

    settings_db = Setting.query.all()
    settings = {s.setting_key: s.setting_value for s in settings_db}
    return render_template('settings.html', settings=settings)
    
@app.route('/export/csv/<int:scan_id>')
def export_csv(scan_id):
    pages = Page.query.filter_by(scan_id=scan_id).all()
    csv_data = generate_csv(pages)
    return Response(
        csv_data,
        mimetype="text/csv",
        headers={"Content-disposition": f"attachment; filename=scan_{scan_id}_export.csv"}
    )

@app.route('/export/json/<int:scan_id>')
def export_json(scan_id):
    pages = Page.query.filter_by(scan_id=scan_id).all()
    json_data = json.dumps([
        {
            'url': p.url,
            'status_code': p.status_code,
            'title': p.title,
            'meta_description': p.meta_description,
            'is_orphan': p.is_orphan,
            'incoming_links': p.incoming_links
        } for p in pages
    ], indent=4)
    return Response(
        json_data,
        mimetype="application/json",
        headers={"Content-disposition": f"attachment; filename=scan_{scan_id}_export.json"}
    )

@app.route('/history')
def history():
    """Displays a paginated history of all scans."""
    # Get the current page number from the URL query string (defaults to 1)
    page = request.args.get('page', 1, type=int)
    per_page = 10  # Number of scans to show per page

    # Use .paginate() instead of .all()
    # error_out=False ensures empty pages don't return a 404, just an empty list
    pagination = Scan.query.order_by(Scan.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )

    return render_template('history.html', pagination=pagination)


def setup_database(app_context):
    """Function to create tables and default settings if they don't exist."""
    with app_context:
        db.create_all()
        
        # Check if settings exist, if not, create them
        if not Setting.query.first():
            default_settings = [
                Setting(setting_key='min_title_length', setting_value='10'),
                Setting(setting_key='max_title_length', setting_value='60'),
                Setting(setting_key='min_desc_length', setting_value='70'),
                Setting(setting_key='max_desc_length', setting_value='160'),
                # ADD THIS NEW SETTING:
                Setting(setting_key='max_image_size_kb', setting_value='150'),
                Setting(setting_key='max_pages_limit', setting_value='200') 
                # Add other default settings here, like for image sizes
            ]
            db.session.bulk_save_objects(default_settings)
            db.session.commit()

if __name__ == '__main__':
    setup_database(app.app_context())
    app.run(debug=True)