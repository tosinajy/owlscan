# crawler.py

import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
import time
import hashlib
from collections import defaultdict

# --- Local Imports ---
from models import Scan, Page, Setting, Link, Image

def normalize_url(url):
    """
    Standardizes URLs to ensure duplicates (like trailing slashes) are treated the same.
    e.g., https://example.com/page/ == https://example.com/page
    """
    parsed = urlparse(url)
    # Lowercase scheme and domain
    scheme = parsed.scheme.lower()
    netloc = parsed.netloc.lower()
    # Strip trailing slash from path
    path = parsed.path
    if path.endswith('/'):
        path = path[:-1]
    
    # Reconstruct without fragment
    return parsed._replace(scheme=scheme, netloc=netloc, path=path, fragment='').geturl()

def check_link_status(url):
    try:
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

def run_crawler(app, db, scan_id):
    with app.app_context():
        try:
            # 1. SETUP
            scan = db.session.get(Scan, scan_id)
            if not scan: return

            scan.status = 'running'
            db.session.commit()

            # NORMALIZE START URL
            start_url = normalize_url(scan.start_url)
            parsed_start = urlparse(start_url)
            domain = parsed_start.netloc
            
            settings_db = Setting.query.all()
            settings = {s.setting_key: s.setting_value for s in settings_db}
            max_image_size = int(settings.get('max_image_size_kb', 150))
            max_pages = int(settings.get('max_pages_limit', 200)) # Default to 200 if missing

            urls_to_visit = set()
            visited_urls = set()
            sitemap_urls = set()
            crawled_urls = set()
            link_graph = defaultdict(set)
            page_data_cache = {}

            # 2. DETECT SITEMAP SCAN (Check original URL for .xml extension before normalization might affect it)
            is_sitemap_scan = urlparse(scan.start_url).path.lower().endswith('.xml')

            if is_sitemap_scan:
                print(f"Starting Sitemap Scan for: {scan.start_url}")
                try:
                    resp = requests.get(scan.start_url, timeout=10)
                    if resp.status_code == 200:
                        soup = BeautifulSoup(resp.content, 'html.parser')
                        for loc in soup.find_all('loc'):
                            # NORMALIZE SITEMAP URLS
                            url = normalize_url(loc.text.strip())
                            urls_to_visit.add(url)
                            sitemap_urls.add(url)
                except Exception as e:
                     print(f"Error fetching target sitemap: {e}")
            else:
                print(f"Starting Recursive Scan for: {start_url}")
                urls_to_visit.add(start_url)
                try:
                    sitemap_url = urljoin(start_url, '/sitemap.xml')
                    sitemap_res = requests.get(sitemap_url, timeout=5)
                    if sitemap_res.status_code == 200:
                        sitemap_soup = BeautifulSoup(sitemap_res.content, 'html.parser')
                        for loc in sitemap_soup.find_all('loc'):
                             # NORMALIZE SITEMAP URLS
                            sitemap_urls.add(normalize_url(loc.text.strip()))
                except Exception:
                    pass

            # 3. CRAWLING LOOP
            while urls_to_visit:
                # IMMEDIATE LIMIT CHECK:
                # If we have already visited enough pages, stop the loop entirely.
                if len(visited_urls) >= max_pages:
                    print(f"Scan {scan_id} reached max page limit of {max_pages}. Stopping.")
                    break

                current_url = urls_to_visit.pop()
                # Ensure we don't crawl outside domain (unless it's a specifically requested sitemap scan URL)
                if urlparse(current_url).netloc != domain and not is_sitemap_scan: continue
                if current_url in visited_urls: continue
                
                visited_urls.add(current_url)
                crawled_urls.add(current_url)
                
                try:
                    response = requests.get(current_url, timeout=10)
                    page_info = { 'scan_id': scan_id, 'url': current_url, 'status_code': response.status_code }
                    
                    if 'text/html' in response.headers.get('Content-Type', ''):
                        soup = BeautifulSoup(response.content, 'html.parser')
                        page_info['title'] = soup.title.string.strip() if soup.title else ''
                        meta_desc = soup.find('meta', attrs={'name': 'description'})
                        page_info['meta_description'] = meta_desc['content'].strip() if meta_desc and meta_desc.get('content') else ''
                        page_info['content_hash'] = hashlib.sha256(soup.get_text(separator=' ', strip=True).encode('utf-8')).hexdigest()

                        # --- Link Analysis ---
                        for link in soup.find_all('a', href=True):
                            href = link['href']
                            if not href or href.startswith(('#', 'mailto:', 'tel:', 'javascript:')): continue
                            
                            full_url = urljoin(current_url, href)
                            
                            # EXCLUDE XML BEFORE NORMALIZATION
                            if urlparse(full_url).path.lower().endswith('.xml'): continue

                            # NORMALIZE DISCOVERED LINK
                            normalized_url = normalize_url(full_url)

                            link_domain = urlparse(normalized_url).netloc
                            if link_domain == domain:
                                link_status = check_link_status(normalized_url)
                                db.session.add(Link(scan_id=scan_id, source_url=current_url, target_url=normalized_url, anchor_text=link.text.strip(), status_code=link_status, is_broken=not (200 <= link_status < 400) and link_status != 0))
                                link_graph[normalized_url].add(current_url)
                                
                                if not is_sitemap_scan and normalized_url not in visited_urls:
                                     total_anticipated = len(visited_urls) + len(urls_to_visit)
                                     if total_anticipated < max_pages:
                                         urls_to_visit.add(normalized_url)

                        # --- Image Analysis ---
                        for img in soup.find_all('img'):
                            img_src = img.get('src')
                            if not img_src: continue
                            # We don't strictly need to normalize image URLs the same way, 
                            # but standardizing them doesn't hurt.
                            img_url = urljoin(current_url, img_src)
                            alt_text = img.get('alt', '').strip()
                            file_size = get_image_size_kb(img_url)
                            db.session.add(Image(scan_id=scan_id, page_url=current_url, image_url=img_url, alt_text=alt_text, file_size_kb=file_size, is_large=(file_size > max_image_size), missing_alt=(not alt_text)))
                    
                    page_data_cache[current_url] = page_info
                except requests.RequestException as e:
                    print(f"Error fetching {current_url}: {e}")
                    page_data_cache[current_url] = { 'scan_id': scan_id, 'url': current_url, 'status_code': 0 }
                
                time.sleep(0.1)

            # 4. DATA SAVING
            all_known_urls = crawled_urls.union(sitemap_urls)
            for url in all_known_urls:
                 # ... (keep existing page saving logic) ...
                 if urlparse(url).path.lower().endswith('.xml'): continue
                 page_info = page_data_cache.get(url, { 'scan_id': scan_id, 'url': url, 'status_code': 404 })
                 page_info['incoming_links'] = len(link_graph.get(url, []))
                 page_info['is_orphan'] = (not is_sitemap_scan) and (url in sitemap_urls) and (url not in crawled_urls)
                 db.session.add(Page(**page_info))
            
            # --- NEW: CALCULATE TOTAL ISSUES BEFORE FINAL COMMIT ---
            # We flush first to ensure all Pages/Links/Images are ready to be counted
            db.session.flush() 
            
            issue_counts = {
                'broken_links': db.session.query(Link).filter_by(scan_id=scan_id, is_broken=True).count(),
                'large_images': db.session.query(Image).filter_by(scan_id=scan_id, is_large=True).count(),
                'missing_alts': db.session.query(Image).filter_by(scan_id=scan_id, missing_alt=True).count(),
                'missing_titles': db.session.query(Page).filter(Page.scan_id==scan_id, (Page.title == '') | (Page.title.is_(None))).count(),
                'missing_descs': db.session.query(Page).filter(Page.scan_id==scan_id, (Page.meta_description == '') | (Page.meta_description.is_(None))).count(),
                'orphaned_pages': db.session.query(Page).filter_by(scan_id=scan_id, is_orphan=True).count()
            }
            
            scan.total_issues = sum(issue_counts.values())
            # -------------------------------------------------------

            scan.status = 'completed'
            db.session.commit()
            
        except Exception as e:
            print(f"CRITICAL FAILURE in scan {scan_id}: {e}")
            scan.status = 'failed'
        finally:
            db.session.commit()