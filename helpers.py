# helpers.py

import csv
from io import StringIO
from collections import defaultdict, Counter
import re
import json
from bs4 import BeautifulSoup
from urllib.parse import urlparse
import textstat
import ollama

STOPWORDS = set(['the', 'be', 'to', 'of', 'and', 'a', 'in', 'that', 'have', 'it', 'for', 'not', 'on', 'with', 'he', 'as', 'you', 'do', 'at', 'this', 'but', 'his', 'by', 'from', 'they', 'we', 'say', 'her', 'she', 'or', 'an', 'will', 'my', 'one', 'all', 'would', 'there', 'their', 'what', 'so', 'up', 'out', 'if', 'about', 'who', 'get', 'which', 'go', 'me', 'when', 'make', 'can', 'like', 'time', 'no', 'just', 'know', 'take', 'people', 'into', 'year', 'your', 'good', 'some', 'could', 'them', 'see', 'other', 'than', 'then', 'now', 'look', 'only', 'come', 'its', 'over', 'think', 'also', 'back', 'after', 'use', 'two', 'how', 'our', 'work', 'first', 'well', 'way', 'even', 'new', 'want', 'because', 'any', 'these', 'give', 'day', 'most', 'us', 'is', 'are', 'was', 'were'])

def get_text_content(soup):
    for script in soup(["script", "style", "header", "footer", "nav", "noscript", "iframe"]):
        script.extract()
    text = soup.get_text(separator=' ')
    return " ".join(text.split())

def extract_keywords(text, n=5):
    words = re.findall(r'\b[a-z]{3,}\b', text.lower())
    meaningful_words = [w for w in words if w not in STOPWORDS]
    return [word for word, count in Counter(meaningful_words).most_common(n)]

def perform_content_analysis(page, domain):
    if not page.html_content: return
    try:
        soup = BeautifulSoup(page.html_content, 'html.parser')
        text_content = get_text_content(soup)

        words = text_content.split()
        page.word_count = len(words)
        page.reading_time_min = round(page.word_count / 200, 1)

        if page.word_count > 5:
             page.flesch_score = textstat.flesch_reading_ease(text_content)
        else:
             page.flesch_score = 0

        page.h1_count = len(soup.find_all('h1'))

        internal = 0
        external = 0
        for link in soup.find_all('a', href=True):
            href = link['href']
            if href.startswith(('#', 'mailto:', 'tel:', 'javascript:')): continue
            if domain in href or href.startswith('/'): internal += 1
            else: external += 1
        page.internal_links_count = internal
        page.external_links_count = external

        keywords = extract_keywords(text_content)
        page.top_keywords = ", ".join(keywords)

    except Exception as e:
        print(f"Error analyzing content for {page.url}: {e}")

def extract_json_from_text(text):
    """Helper to find and parse a JSON list from a string."""
    try:
        # Look for a list pattern [...]
        match = re.search(r'\[.*\]', text, re.DOTALL)
        if match:
            return json.loads(match.group(0))
        
        # Fallback: try cleaning markdown if regex failed
        clean_text = text.replace('```json', '').replace('```', '').strip()
        return json.loads(clean_text)
    except Exception:
        return None

def check_spelling_ai(page):
    """Uses Ollama (Gemma) to check for spelling and grammar errors."""
    if not page.html_content: return
    
    try:
        soup = BeautifulSoup(page.html_content, 'html.parser')
        text_content = get_text_content(soup)[:2000] 
        
        prompt = (
            f"Identify spelling and grammar errors in the following text. "
            f"Return ONLY a JSON list of objects, where each object has 'error' (the mistake) "
            f"and 'context' (a short excerpt surrounding the mistake). "
            f"If there are no errors, return an empty list []. "
            f"Do not include any other text.\n\nText:\n{text_content}"
        )
        
        response = ollama.chat(model='gemma2:2b', messages=[{'role': 'user', 'content': prompt}])
        content = response['message']['content']
        
        errors = extract_json_from_text(content)
        
        if isinstance(errors, list) and len(errors) > 0:
            page.spelling_issues_count = len(errors)
            page.spelling_examples = json.dumps(errors)
        elif errors is None:
             print(f"Failed to parse AI spelling response for {page.url}")

    except Exception as e:
        print(f"AI Spell Check Error for {page.url}: {e}")

def generate_advanced_seo_ai(page):
    """Uses Ollama (Gemma) to generate advanced SEO recommendations."""
    if not page.html_content: return

    try:
        soup = BeautifulSoup(page.html_content, 'html.parser')
        # We need structure for SEO, not just text
        for script in soup(["script", "style", "svg", "noscript"]):
            script.extract()
        
        html_excerpt = str(soup)[:3000] # Limit tokens
        
        prompt = (
            f"Analyze this HTML content for advanced SEO optimization opportunities beyond basic tags. "
            f"Focus on semantic HTML, keyword usage, content structure, or opportunities for rich snippets. "
            f"Return ONLY a JSON list of 1 to 3 short, actionable strings (e.g. ['Use <article> tags', 'Add schema markup']). "
            f"Do not include any other text.\n\nHTML:\n{html_excerpt}"
        )
        
        response = ollama.chat(model='gemma2:2b', messages=[{'role': 'user', 'content': prompt}])
        content = response['message']['content']
        
        recs = extract_json_from_text(content)
        
        if isinstance(recs, list) and len(recs) > 0:
            page.advanced_seo_recs = json.dumps(recs)
        elif recs is None:
            print(f"Failed to parse AI SEO response for {page.url}")
            
    except Exception as e:
        print(f"AI SEO Error for {page.url}: {e}")

def generate_seo_recommendations(page, settings):
    recs = []
    min_title = int(settings.get('min_title_length', 10))
    min_desc = int(settings.get('min_desc_length', 70))
    
    if not page.title: recs.append("Add a Title tag.")
    elif len(page.title) < min_title: recs.append("Lengthen Title tag.")
    
    if not page.meta_description: recs.append("Add a Meta Description.")
    elif len(page.meta_description) < min_desc: recs.append("Lengthen Meta Description.")
        
    if page.h1_count == 0: recs.append("Add an H1 tag.")
    elif page.h1_count > 1: recs.append("Use only one H1 tag.")
        
    if page.word_count < 300: recs.append("Add more content (>300 words).")
        
    if page.flesch_score < 50 and page.word_count > 50: recs.append("Simplify text (readability).")
        
    return recs[:3]

def analyze_results(pages, settings):
    analysis = {
        'total_pages': len(pages),
        'missing_titles': [], 'duplicate_titles': defaultdict(list), 'short_titles': [], 'long_titles': [],
        'missing_descriptions': [], 'duplicate_descriptions': defaultdict(list), 'short_descriptions': [], 'long_descriptions': [],
        'duplicate_content': defaultdict(list), 'orphaned_pages': [],
        'thin_content_pages': [], 'slow_read_pages': [], 'complex_readability': [], 'missing_h1': [], 'multiple_h1': [],
        'spelling_issues': [], 'page_seo_recommendations': [], 'advanced_seo_recommendations': [],
        'broken_links': [], 'rate_limit_errors': []
    }
    
    title_map, desc_map, content_map = defaultdict(list), defaultdict(list), defaultdict(list)
    min_title, max_title = int(settings.get('min_title_length', 10)), int(settings.get('max_title_length', 60))
    min_desc, max_desc = int(settings.get('min_desc_length', 70)), int(settings.get('max_desc_length', 160))

    for page in pages:
        if page.status_code == 404:
            analysis['broken_links'].append(page)
        elif page.status_code == 429:
            analysis['rate_limit_errors'].append(page)

        recs = generate_seo_recommendations(page, settings)
        if recs:
            analysis['page_seo_recommendations'].append({'url': page.url, 'recs': recs})
            
        # Collect Advanced AI Recs if they exist
        if page.advanced_seo_recs:
             try:
                 ai_recs = json.loads(page.advanced_seo_recs)
                 analysis['advanced_seo_recommendations'].append({'url': page.url, 'recs': ai_recs})
             except: pass

        if page.is_orphan: analysis['orphaned_pages'].append(page)
        if not page.title: analysis['missing_titles'].append(page)
        else:
            if len(page.title) < min_title: analysis['short_titles'].append(page)
            if len(page.title) > max_title: analysis['long_titles'].append(page)
            title_map[page.title].append(page)
        if not page.meta_description: analysis['missing_descriptions'].append(page)
        else:
            if len(page.meta_description) < min_desc: analysis['short_descriptions'].append(page)
            if len(page.meta_description) > max_desc: analysis['long_descriptions'].append(page)
            desc_map[page.meta_description].append(page)
        if page.content_hash: content_map[page.content_hash].append(page)

        if page.status_code == 200:
            if page.word_count < 300: analysis['thin_content_pages'].append(page)
            if page.reading_time_min > 10: analysis['slow_read_pages'].append(page)
            if page.word_count > 50 and page.flesch_score < 50: analysis['complex_readability'].append(page)
            if page.h1_count == 0: analysis['missing_h1'].append(page)
            if page.h1_count > 1: analysis['multiple_h1'].append(page)
            if page.spelling_issues_count > 0: analysis['spelling_issues'].append(page)

    analysis['duplicate_titles'] = {title: page_list for title, page_list in title_map.items() if len(page_list) > 1}
    analysis['duplicate_descriptions'] = {desc: page_list for desc, page_list in desc_map.items() if len(page_list) > 1}
    analysis['duplicate_content'] = {h: page_list for h, page_list in content_map.items() if len(page_list) > 1}
    
    return analysis

def generate_csv(pages):
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(['URL', 'Status', 'Title', 'Meta Description', 'Words', 'Read Time (min)', 'Flesch Score', 'H1 Count', 'Int Links', 'Ext Links', 'Spelling Issues', 'Top Keywords'])
    for p in pages:
        writer.writerow([p.url, p.status_code, p.title, p.meta_description, p.word_count, p.reading_time_min, p.flesch_score, p.h1_count, p.internal_links_count, p.external_links_count, p.spelling_issues_count, p.top_keywords])
    return output.getvalue()