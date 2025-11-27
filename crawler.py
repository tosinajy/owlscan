# crawler.py

import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
import time
import hashlib
from collections import defaultdict
from sqlalchemy import desc
import mimetypes

# --- Local Imports ---
from models import Scan, Page, Setting, Image

def normalize_url(url):
    parsed = urlparse(url)
    scheme = parsed.scheme.lower()
    netloc = parsed.netloc.lower()
    path = parsed.path
    if path.endswith('/'):
        path = path[:-1]
    return parsed._replace(scheme=scheme, netloc=netloc, path=path, fragment='').geturl()

def determine_category(url, content_type_header):
    path = urlparse(url).path.lower()
    if path.endswith('.xml') or 'xml' in content_type_header:
        return 'xml'
    media_extensions = ('.jpg', '.jpeg', '.png', '.gif', '.svg', '.webp', '.pdf', '.mp4', '.mp3', '.zip')
    if path.endswith(media_extensions) or any(t in content_type_header for t in ['image/', 'video/', 'application/pdf']):
        return 'media'
    if 'text/html' in content_type_header:
        return 'page'
    return 'other'

def get_image_size_kb(url):
    try:
        response = requests.head(url, timeout=5, allow_redirects=True)
        size_in_bytes = int(response.headers.get('Content-Length', 0))
        return round(size_in_bytes / 1024)
    except (requests.RequestException, ValueError):
        return 0

def get_previous_page_hashes(db, current_scan):
    prev_scan = db.session.query(Scan).filter(
        Scan.start_url == current_scan.start_url,
        Scan.status == 'completed',
        Scan.id != current_scan.id
    ).order_by(desc(Scan.created_at)).first()
    if not prev_scan: return {}
    return {p.url: p.content_hash for p in prev_scan.pages}

def run_crawler(app, db, scan_id):
    with app.app_context():
        try:
            scan = db.session.get(Scan, scan_id)
            if not scan: return

            scan.status = 'crawling'
            db.session.commit()

            start_url = normalize_url(scan.start_url)
            parsed_start = urlparse(start_url)
            domain = parsed_start.netloc
            
            settings_db = Setting.query.all()
            settings = {s.setting_key: s.setting_value for s in settings_db}
            
            max_image_size = int(settings.get('max_image_size_kb', 150))
            max_pages_limit = int(settings.get('max_pages_limit', 200))
            request_interval = int(settings.get('request_interval', 5))

            prev_hashes = get_previous_page_hashes(db, scan)

            urls_to_visit = set([start_url])
            visited_urls = set()
            link_graph = defaultdict(set)
            page_data_cache = {}
            crawled_pages_count = 0 

            # SITEMAP CHECK
            if start_url.endswith('.xml'):
                try:
                    resp = requests.get(start_url, timeout=10)
                    time.sleep(request_interval)
                    if resp.status_code == 200:
                        soup = BeautifulSoup(resp.content, 'xml')
                        for loc in soup.find_all('loc'):
                            url = normalize_url(loc.text.strip())
                            if urlparse(url).netloc == domain:
                                urls_to_visit.add(url)
                except Exception as e:
                     print(f"Error fetching sitemap: {e}")

            # CRAWLING LOOP
            pages_processed = 0 
            while urls_to_visit:
                current_url = urls_to_visit.pop()
                if current_url in visited_urls: continue
                if urlparse(current_url).netloc != domain: continue

                visited_urls.add(current_url)

                try:
                    response = requests.get(current_url, timeout=10, stream=True) 
                    content_type = response.headers.get('Content-Type', '').lower()
                    status_code = response.status_code
                    
                    category = determine_category(current_url, content_type)

                    if category == 'page':
                        if crawled_pages_count >= max_pages_limit: continue
                        crawled_pages_count += 1

                    page_info = { 
                        'scan_id': scan_id, 'url': current_url, 
                        'status_code': status_code, 'category': category 
                    }

                    if status_code == 200 and category == 'page':
                        html_content = response.text 
                        page_info['html_content'] = html_content
                        
                        soup = BeautifulSoup(html_content, 'html.parser')
                        page_info['title'] = soup.title.string.strip() if soup.title else ''
                        meta_desc = soup.find('meta', attrs={'name': 'description'})
                        page_info['meta_description'] = meta_desc['content'].strip() if meta_desc and meta_desc.get('content') else ''
                        page_info['content_hash'] = hashlib.sha256(soup.get_text(separator=' ', strip=True).encode('utf-8')).hexdigest()

                        if current_url not in prev_hashes:
                            scan.new_urls_count += 1
                            page_info['crawl_status'] = 'new'
                        elif prev_hashes[current_url] != page_info['content_hash']:
                            scan.updated_urls_count += 1
                            page_info['crawl_status'] = 'updated'
                        else:
                            scan.existing_urls_count += 1
                            page_info['crawl_status'] = 'existing'

                        # RECURSIVE LINK DISCOVERY (Internal Only) - No DB Insert for Links
                        for link in soup.find_all('a', href=True):
                            href = link['href']
                            if not href or href.startswith(('#', 'mailto:', 'tel:', 'javascript:')): continue
                            full_url = urljoin(current_url, href)
                            normalized_url = normalize_url(full_url)
                            if urlparse(normalized_url).netloc == domain:
                                link_graph[normalized_url].add(current_url)
                                if normalized_url not in visited_urls:
                                    urls_to_visit.add(normalized_url)

                        # IMAGE ANALYSIS (Internal Only) - Save to DB
                        for img in soup.find_all('img'):
                            img_src = img.get('src')
                            if not img_src: continue
                            img_url = urljoin(current_url, img_src)
                            if urlparse(img_url).netloc == domain:
                                file_size = get_image_size_kb(img_url)
                                is_large = file_size > max_image_size
                                db.session.add(Image(
                                    scan_id=scan_id, 
                                    page_url=current_url, 
                                    image_url=img_url, 
                                    alt_text=img.get('alt', '').strip(), 
                                    file_size_kb=file_size, 
                                    is_large=is_large, 
                                    missing_alt=(not img.get('alt', '').strip())
                                ))
                    
                    elif category != 'page':
                         scan.existing_urls_count += 1
                         page_info['crawl_status'] = 'existing'

                    page_data_cache[current_url] = page_info
                    
                    pages_processed += 1
                    if pages_processed % 5 == 0:
                        db.session.commit()

                except requests.RequestException as e:
                    print(f"Error fetching {current_url}: {e}")
                    page_data_cache[current_url] = { 'scan_id': scan_id, 'url': current_url, 'status_code': 0, 'category': 'other' }
                
                time.sleep(request_interval)

            for url, data in page_data_cache.items():
                 data['incoming_links'] = len(link_graph.get(url, []))
                 data['is_orphan'] = (data['incoming_links'] == 0 and url != start_url)
                 db.session.add(Page(**data))
            
            scan.status = 'crawled'
            db.session.commit()
            
        except Exception as e:
            print(f"CRITICAL FAILURE in scan {scan_id}: {e}")
            scan.status = 'failed'
            db.session.commit()