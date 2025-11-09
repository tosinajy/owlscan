# helpers.py

import csv
from io import StringIO
from collections import defaultdict, Counter
import re
import json
from bs4 import BeautifulSoup
from urllib.parse import urlparse
import textstat
from spellchecker import SpellChecker

STOPWORDS = set(['the', 'be', 'to', 'of', 'and', 'a', 'in', 'that', 'have', 'it', 'for', 'not', 'on', 'with', 'he', 'as', 'you', 'do', 'at', 'this', 'but', 'his', 'by', 'from', 'they', 'we', 'say', 'her', 'she', 'or', 'an', 'will', 'my', 'one', 'all', 'would', 'there', 'their', 'what', 'so', 'up', 'out', 'if', 'about', 'who', 'get', 'which', 'go', 'me', 'when', 'make', 'can', 'like', 'time', 'no', 'just', 'know', 'take', 'people', 'into', 'year', 'your', 'good', 'some', 'could', 'them', 'see', 'other', 'than', 'then', 'now', 'look', 'only', 'come', 'its', 'over', 'think', 'also', 'back', 'after', 'use', 'two', 'how', 'our', 'work', 'first', 'well', 'way', 'even', 'new', 'want', 'because', 'any', 'these', 'give', 'day', 'most', 'us', 'is', 'are', 'was', 'were'])

spell = SpellChecker()

def get_text_content(soup):
    for script in soup(["script", "style", "header", "footer", "nav", "noscript", "iframe"]):
        script.extract()
    text = soup.get_text()
    lines = (line.strip() for line in text.splitlines())
    chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
    text = '\n'.join(chunk for chunk in chunks if chunk)
    return text

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

def check_spelling_grammar(page):
    """Performs spelling and basic grammar checks on page content."""
    if not page.html_content: return
    try:
        soup = BeautifulSoup(page.html_content, 'html.parser')
        text_content = get_text_content(soup)

        # Spelling Check
        words = re.findall(r'\b[a-zA-Z]{4,}\b', text_content) 
        misspelled = spell.unknown(words)
        page.spelling_issues_count = len(misspelled)
        page.spelling_examples = ", ".join(list(misspelled)[:5])

        # Grammar Checks with Context Capture
        grammar_contexts = []
        
        # Helper to capture context around a match
        def capture_context(match_obj, text, window=50):
            start, end = match_obj.span()
            c_start = max(0, start - window)
            c_end = min(len(text), end + window)
            # FIX: Perform replacement outside f-string to avoid SyntaxError in older Python versions
            snippet = text[c_start:c_end].replace('\n', ' ')
            return f"...{snippet}..."

        # 1. "a" before vowel sound
        for m in re.finditer(r'\b(a\s+[aeiou][a-z]+)\b', text_content, re.IGNORECASE):
             grammar_contexts.append(capture_context(m, text_content))

        # 2. "an" before consonant sound
        for m in re.finditer(r'\b(an\s+[^aeiou\s][a-z]+)\b', text_content, re.IGNORECASE):
             grammar_contexts.append(capture_context(m, text_content))

        # 3. Repeated words
        for m in re.finditer(r'\b(\w+)\s+\1\b', text_content, re.IGNORECASE):
             grammar_contexts.append(capture_context(m, text_content))

        page.grammar_issues_count = len(grammar_contexts)
        # Store top 5 contexts as a JSON string
        page.grammar_error_context = json.dumps(grammar_contexts[:5])

    except Exception as e:
        print(f"Error checking spelling/grammar for {page.url}: {e}")

def analyze_results(pages, settings):
    analysis = {
        'total_pages': len(pages),
        'missing_titles': [], 'duplicate_titles': defaultdict(list), 'short_titles': [], 'long_titles': [],
        'missing_descriptions': [], 'duplicate_descriptions': defaultdict(list), 'short_descriptions': [], 'long_descriptions': [],
        'duplicate_content': defaultdict(list), 'orphaned_pages': [],
        'thin_content_pages': [], 'slow_read_pages': [], 'complex_readability': [], 'missing_h1': [], 'multiple_h1': [],
        'spelling_issues': [], 'grammar_issues': []
    }
    
    title_map, desc_map, content_map = defaultdict(list), defaultdict(list), defaultdict(list)
    min_title, max_title = int(settings.get('min_title_length', 10)), int(settings.get('max_title_length', 60))
    min_desc, max_desc = int(settings.get('min_desc_length', 70)), int(settings.get('max_desc_length', 160))

    for page in pages:
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
            if page.grammar_issues_count > 0: analysis['grammar_issues'].append(page)

    analysis['duplicate_titles'] = {title: page_list for title, page_list in title_map.items() if len(page_list) > 1}
    analysis['duplicate_descriptions'] = {desc: page_list for desc, page_list in desc_map.items() if len(page_list) > 1}
    analysis['duplicate_content'] = {h: page_list for h, page_list in content_map.items() if len(page_list) > 1}
    
    return analysis

def generate_csv(pages):
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(['URL', 'Status', 'Title', 'Meta Description', 'Words', 'Read Time (min)', 'Flesch Score', 'H1 Count', 'Int Links', 'Ext Links', 'Spelling Issues', 'Grammar Issues', 'Top Keywords'])
    for p in pages:
        writer.writerow([p.url, p.status_code, p.title, p.meta_description, p.word_count, p.reading_time_min, p.flesch_score, p.h1_count, p.internal_links_count, p.external_links_count, p.spelling_issues_count, p.grammar_issues_count, p.top_keywords])
    return output.getvalue()