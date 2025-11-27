# app.py

from flask import (
    Flask, render_template, request, jsonify, redirect, url_for, Response, flash
)
from threading import Thread
from sqlalchemy import func, desc
import json
from urllib.parse import urlparse
import ollama
from bs4 import BeautifulSoup

# --- Local Imports ---
from config import Config
from models import db, Scan, Page, Setting, Link, Image
from crawler import run_crawler
from helpers import analyze_results, generate_csv, perform_content_analysis, check_spelling_grammar

app = Flask(__name__)
app.config.from_object(Config)
db.init_app(app)

# --- Helper for Chat Context ---
def build_site_context(scan_id):
    scan = db.session.get(Scan, scan_id)
    if not scan: return ""
    
    settings = {s.setting_key: s.setting_value for s in Setting.query.all()}
    
    context = f"You are an AI Web Analyst. You are analyzing the website: {scan.start_url}\n"
    context += "Use the following Scan Data to answer the user's questions truthfully.\n\n"
    
    context += f"=== SCAN SUMMARY ===\n"
    context += f"URL: {scan.start_url}\n"
    context += f"Scan Date: {scan.created_at.strftime('%Y-%m-%d')}\n"
    context += f"Total Pages Scanned: {len(scan.pages)}\n"
    context += f"Total Issues Detected: {scan.total_issues}\n"
    
    if scan.analysis_json:
        try:
            analysis = json.loads(scan.analysis_json)
            context += f"\n=== TECHNICAL ISSUES ===\n"
            context += f"- Broken Links: {len(analysis.get('broken_links', []))}\n"
            context += f"- Rate Limit Errors (429): {len(analysis.get('rate_limit_errors', []))}\n"
            context += f"- Pages Missing Titles: {len(analysis.get('missing_titles', []))}\n"
            context += f"- Pages Missing Meta Descriptions: {len(analysis.get('missing_descriptions', []))}\n"
            context += f"- Images Missing Alt Text: {len(analysis.get('missing_alt_images', []))}\n"
            context += f"- Large Images (> {settings.get('max_image_size_kb')}KB): {len(analysis.get('large_images', []))}\n"
            context += f"- Thin Content Pages (< 300 words): {len(analysis.get('thin_content_pages', []))}\n"
            context += f"- Pages with Spelling Issues: {len(analysis.get('spelling_issues', []))}\n"
        except: pass

    # Add Homepage Content for context (limited to ~3000 chars for lightweight models)
    home_page = Page.query.filter_by(scan_id=scan_id, url=scan.start_url).first()
    if not home_page and scan.start_url.endswith('/'):
         home_page = Page.query.filter_by(scan_id=scan_id, url=scan.start_url[:-1]).first()
    elif not home_page and not scan.start_url.endswith('/'):
         home_page = Page.query.filter_by(scan_id=scan_id, url=scan.start_url + '/').first()

    if home_page and home_page.html_content:
        try:
            soup = BeautifulSoup(home_page.html_content, 'html.parser')
            for script in soup(["script", "style", "nav", "footer", "svg", "noscript"]): script.extract()
            text = soup.get_text(separator=' ', strip=True)[:3000]
            context += f"\n=== HOMEPAGE CONTENT EXCERPT ===\n{text}\n"
        except: pass
        
    return context

# --- Routes ---
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/documentation')
def documentation():
    return render_template('documentation.html')

@app.route('/start_scan', methods=['POST'])
def start_scan():
    start_url = request.form.get('url')
    if not start_url: return jsonify({'error': 'URL is required'}), 400
    new_scan = Scan(start_url=start_url, status='crawling')
    db.session.add(new_scan)
    db.session.commit()
    Thread(target=run_crawler, args=(app, db, new_scan.id), daemon=True).start()
    return jsonify({'scan_id': new_scan.id})

@app.route('/scan/<int:scan_id>')
def view_results(scan_id):
    scan = db.session.get(Scan, scan_id)
    if not scan: return "Scan not found", 404
    if scan.status == 'crawled': return redirect(url_for('view_scan_data', scan_id=scan_id))
    elif scan.status == 'completed':
        settings = {s.setting_key: s.setting_value for s in Setting.query.all()}
        analysis = json.loads(scan.analysis_json) if scan.analysis_json else {}
        pages = Page.query.filter_by(scan_id=scan.id).order_by(Page.url).all()
        return render_template('results.html', scan=scan, analysis=analysis, settings=settings, pages=pages)
    else:
        return render_template('results.html', scan=scan, analysis=None, settings={})

@app.route('/scan_data/<int:scan_id>')
def view_scan_data(scan_id):
    scan = db.session.get(Scan, scan_id)
    if not scan: return "Scan not found", 404
    pages = Page.query.filter_by(scan_id=scan.id).order_by(Page.url).all()
    return render_template('intermediary_results.html', scan=scan, pages=pages)

# --- NEW CHAT ROUTES ---
@app.route('/chat/<int:scan_id>')
def chat_page(scan_id):
    """Renders the chat interface for a specific scan."""
    scan = db.session.get(Scan, scan_id)
    if not scan: return "Scan not found", 404
    return render_template('chat.html', scan=scan)

@app.route('/api/chat', methods=['POST'])
def api_chat():
    """Handles chat messages using Ollama."""
    data = request.json
    scan_id = data.get('scan_id')
    user_message = data.get('message')
    history = data.get('history', [])
    
    try:
        system_prompt = build_site_context(scan_id)
        messages = [{'role': 'system', 'content': system_prompt}] + history + [{'role': 'user', 'content': user_message}]
        
        # Using 'gemma2:2b' as a robust lightweight model. 
        # Change to 'llama3.2:1b', 'qwen2.5:0.5b', or your preferred model name if different.
        response = ollama.chat(model='gemma2:2b', messages=messages)
        
        return jsonify({'response': response['message']['content']})
    except Exception as e:
        print(f"Chat Error: {e}")
        return jsonify({'error': str(e)}), 500
# -----------------------

@app.route('/analyze/<int:scan_id>', methods=['POST'])
def perform_analysis(scan_id):
    scan = db.session.get(Scan, scan_id)
    if not scan or scan.status != 'crawled': return jsonify({'error': 'Invalid scan state'}), 400

    scan.status = 'analyzing'
    db.session.commit()

    try:
        settings = {s.setting_key: s.setting_value for s in Setting.query.all()}
        pages = Page.query.filter_by(scan_id=scan.id).all()
        domain = urlparse(scan.start_url).netloc

        for page in pages:
            if page.status_code == 200:
                perform_content_analysis(page, domain)
                check_spelling_grammar(page)
        
        db.session.commit() 

        analysis = analyze_results(pages, settings)
        
        def serialize_page_list(page_list):
             return [{'url': p.url, 'title': p.title, 'word_count': p.word_count, 'flesch_score': p.flesch_score} for p in page_list]

        analysis['rate_limit_errors'] = [{'source_url': l.source_url, 'target_url': l.target_url, 'anchor_text': l.anchor_text, 'status_code': l.status_code} for l in Link.query.filter_by(scan_id=scan.id, status_code=429).all()]
        analysis['broken_links'] = [{'source_url': l.source_url, 'target_url': l.target_url, 'anchor_text': l.anchor_text, 'status_code': l.status_code} for l in Link.query.filter(Link.scan_id == scan.id, Link.is_broken == True, Link.status_code != 429).all()]
        analysis['large_images'] = [{'image_url': i.image_url, 'page_url': i.page_url, 'file_size_kb': i.file_size_kb} for i in Image.query.filter_by(scan_id=scan.id, is_large=True).all()]
        analysis['missing_alt_images'] = [{'image_url': i.image_url, 'page_url': i.page_url} for i in Image.query.filter_by(scan_id=scan.id, missing_alt=True).all()]

        for key in ['missing_titles', 'short_titles', 'long_titles', 'missing_descriptions', 'short_descriptions', 'long_descriptions', 'orphaned_pages']:
             analysis[key] = [{'url': p.url, 'title': p.title, 'meta_description': p.meta_description} for p in analysis[key]]
        
        for key in ['thin_content_pages', 'slow_read_pages', 'complex_readability', 'missing_h1', 'multiple_h1']:
            analysis[key] = serialize_page_list(analysis[key])

        analysis['spelling_issues'] = [{'url': p.url, 'count': p.spelling_issues_count, 'examples': p.spelling_examples} for p in analysis['spelling_issues']]
        analysis['grammar_issues'] = [{'url': p.url, 'count': p.grammar_issues_count, 'context': json.loads(p.grammar_error_context) if p.grammar_error_context else []} for p in analysis['grammar_issues']]

        for key in ['duplicate_titles', 'duplicate_descriptions', 'duplicate_content']:
            analysis[key] = {k: [{'url': p.url} for p in v] for k, v in analysis[key].items()}

        scan.total_issues = sum([len(analysis[k]) for k in [
            'broken_links', 'large_images', 'missing_alt_images', 
            'missing_titles', 'missing_descriptions', 'orphaned_pages',
            'thin_content_pages', 'complex_readability', 'missing_h1', 'multiple_h1',
            'spelling_issues', 'grammar_issues'
        ]])
        
        scan.analysis_json = json.dumps(analysis)
        scan.status = 'completed'
        db.session.commit()
        return jsonify({'status': 'success'})
    except Exception as e:
        print(f"Analysis Failed: {e}")
        scan.status = 'failed'
        db.session.commit()
        return jsonify({'error': str(e)}), 500

@app.route('/scan_status/<int:scan_id>')
def scan_status(scan_id):
    scan = db.session.get(Scan, scan_id)
    if not scan:
        return jsonify({'status': 'not_found'})
    
    # 1. Get current progress
    current_count = scan.new_urls_count + scan.updated_urls_count + scan.existing_urls_count
    
    # 2. Get the max limit to calculate percentage
    # We fetch it freshly here in case it changed, or you can cache it.
    max_pages_setting = Setting.query.filter_by(setting_key='max_pages_limit').first()
    max_pages = int(max_pages_setting.setting_value) if max_pages_setting else 200

    return jsonify({
        'status': scan.status,
        'current': current_count,
        'total': max_pages
    })

@app.route('/history')
def history():
    page = request.args.get('page', 1, type=int)
    per_page = 5
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
    data = []
    for p in pages:
        data.append({
            'url': p.url, 'status_code': p.status_code, 'title': p.title, 'meta_description': p.meta_description, 
            'is_orphan': p.is_orphan, 'incoming_links': p.incoming_links,
            'metrics': {
                'word_count': p.word_count, 'reading_time_min': p.reading_time_min, 'flesch_score': p.flesch_score,
                'h1_count': p.h1_count, 'internal_links_on_page': p.internal_links_count, 'external_links_on_page': p.external_links_count,
                'top_keywords': p.top_keywords,
                'spelling_issues_count': p.spelling_issues_count, 'grammar_issues_count': p.grammar_issues_count
            }
        })
    return Response(json.dumps(data, indent=4), mimetype="application/json", headers={"Content-disposition": f"attachment; filename=scan_{scan_id}_export.json"})

def setup_database(app_context):
    with app_context:
        db.create_all()
        if not Setting.query.first():
            db.session.bulk_save_objects([Setting(setting_key='min_title_length', setting_value='10'), Setting(setting_key='max_title_length', setting_value='60'), Setting(setting_key='min_desc_length', setting_value='70'), Setting(setting_key='max_desc_length', setting_value='160'), Setting(setting_key='max_image_size_kb', setting_value='150'), Setting(setting_key='max_pages_limit', setting_value='200')])
            db.session.commit()

if __name__ == '__main__':
    setup_database(app.app_context())
    app.run(debug=True)