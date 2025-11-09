# crawler.py

import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
import time
import hashlib
from collections import defaultdict
from sqlalchemy import desc

# --- Local Imports ---
from models import Scan, Page, Setting, Link, Image

def normalize_url(url):
    parsed = urlparse(url)
    scheme = parsed.scheme.lower()
    netloc = parsed.netloc.lower()
    path = parsed.path
    if path.endswith('/'):
        path = path[:-1]
    return parsed._replace(scheme=scheme, netloc=netloc, path=path, fragment='').geturl()

def check_link_status(url):
    try:
        # Use a distinct user agent or handle rate limits if possible, 
        # but for now we just capture the 429 status if it happens.
        response = requests.head(url, timeout=5, allow_redirects=True)
        return response.status_code
    except requests.RequestException:
        return 0

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

    if not prev_scan:
        return {}
    return {p.url: p.content_hash for p in prev_scan.pages}

def run_crawler(app, db, scan_id):
    with app.app_context():
        try:
            # 1. SETUP
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
            max_pages = int(settings.get('max_pages_limit', 200))

            prev_hashes = get_previous_page_hashes(db, scan)

            urls_to_visit = set()
            visited_urls = set()
            sitemap_urls = set()
            crawled_urls = set()
            link_graph = defaultdict(set)
            page_data_cache = {}

            # 2. DETECT SITEMAP
            is_sitemap_scan = urlparse(scan.start_url).path.lower().endswith('.xml')

            if is_sitemap_scan:
                try:
                    resp = requests.get(scan.start_url, timeout=10)
                    if resp.status_code == 200:
                        soup = BeautifulSoup(resp.content, 'xml')
                        for loc in soup.find_all('loc'):
                            urls_to_visit.add(normalize_url(loc.text.strip()))
                            sitemap_urls.add(normalize_url(loc.text.strip()))
                except Exception as e:
                     print(f"Error fetching sitemap: {e}")
            else:
                urls_to_visit.add(start_url)
                try:
                    sitemap_url = urljoin(start_url, '/sitemap.xml')
                    sitemap_res = requests.get(sitemap_url, timeout=5)
                    if sitemap_res.status_code == 200:
                        sitemap_soup = BeautifulSoup(sitemap_res.content, 'xml')
                        for loc in sitemap_soup.find_all('loc'):
                            sitemap_urls.add(normalize_url(loc.text.strip()))
                except Exception:
                    pass

            # 3. CRAWLING LOOP
            while urls_to_visit:
                if len(visited_urls) >= max_pages: break

                current_url = urls_to_visit.pop()
                if urlparse(current_url).netloc != domain and not is_sitemap_scan: continue
                if current_url in visited_urls: continue
                
                visited_urls.add(current_url)
                crawled_urls.add(current_url)
                
                try:
                    response = requests.get(current_url, timeout=10)
                    page_info = { 'scan_id': scan_id, 'url': current_url, 'status_code': response.status_code }
                    
                    if response.status_code == 200 and 'text/html' in response.headers.get('Content-Type', ''):
                        # NEW: Save HTML content
                        page_info['html_content'] = response.text
                        
                        soup = BeautifulSoup(response.content, 'html.parser')
                        page_info['title'] = soup.title.string.strip() if soup.title else ''
                        meta_desc = soup.find('meta', attrs={'name': 'description'})
                        page_info['meta_description'] = meta_desc['content'].strip() if meta_desc and meta_desc.get('content') else ''
                        page_info['content_hash'] = hashlib.sha256(soup.get_text(separator=' ', strip=True).encode('utf-8')).hexdigest()

                        if current_url not in prev_hashes:
                            page_info['crawl_status'] = 'new'
                            scan.new_urls_count += 1
                        elif prev_hashes[current_url] != page_info['content_hash']:
                            page_info['crawl_status'] = 'updated'
                            scan.updated_urls_count += 1
                        else:
                            page_info['crawl_status'] = 'existing'
                            scan.existing_urls_count += 1

                        # Link Analysis
                        for link in soup.find_all('a', href=True):
                            href = link['href']
                            if not href or href.startswith(('#', 'mailto:', 'tel:', 'javascript:')): continue
                            full_url = urljoin(current_url, href)
                            if urlparse(full_url).path.lower().endswith('.xml'): continue
                            normalized_url = normalize_url(full_url)
                            
                            if urlparse(normalized_url).netloc == domain:
                                link_status = check_link_status(normalized_url)
                                # Note: We still mark 429 as broken here for raw data, but will filter later in analysis
                                is_broken = not (200 <= link_status < 400) and link_status != 0
                                db.session.add(Link(scan_id=scan_id, source_url=current_url, target_url=normalized_url, anchor_text=link.text.strip(), status_code=link_status, is_broken=is_broken))
                                link_graph[normalized_url].add(current_url)
                                if not is_sitemap_scan and normalized_url not in visited_urls and (len(visited_urls) + len(urls_to_visit) < max_pages):
                                     urls_to_visit.add(normalized_url)

                        # Image Analysis
                        for img in soup.find_all('img'):
                            img_src = img.get('src')
                            if not img_src: continue
                            img_url = urljoin(current_url, img_src)
                            file_size = get_image_size_kb(img_url)
                            db.session.add(Image(scan_id=scan_id, page_url=current_url, image_url=img_url, alt_text=img.get('alt', '').strip(), file_size_kb=file_size, is_large=(file_size > max_image_size), missing_alt=(not img.get('alt', '').strip())))
                    
                    page_data_cache[current_url] = page_info
                except requests.RequestException as e:
                    print(f"Error fetching {current_url}: {e}")
                    page_data_cache[current_url] = { 'scan_id': scan_id, 'url': current_url, 'status_code': 0, 'crawl_status': 'existing' }
                
                time.sleep(0.1)

            # 4. SAVE INTERMEDIARY RAW DATA
            for url in crawled_urls.union(sitemap_urls):
                 if urlparse(url).path.lower().endswith('.xml'): continue
                 page_info = page_data_cache.get(url, { 'scan_id': scan_id, 'url': url, 'status_code': 404, 'crawl_status': 'existing' })
                 page_info['incoming_links'] = len(link_graph.get(url, []))
                 page_info['is_orphan'] = (not is_sitemap_scan) and (url in sitemap_urls) and (url not in crawled_urls)
                 db.session.add(Page(**page_info))
            
            scan.status = 'crawled'
            db.session.commit()
            
        except Exception as e:
            print(f"CRITICAL FAILURE in scan {scan_id}: {e}")
            scan.status = 'failed'
            db.session.commit()