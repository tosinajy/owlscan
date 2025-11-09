# helpers.py

import csv
from io import StringIO
from collections import defaultdict

def analyze_results(pages, settings):
    """Process the list of pages to generate a comprehensive analysis report."""
    analysis = {
        'total_pages': len(pages),
        'missing_titles': [], 'duplicate_titles': defaultdict(list), 'short_titles': [], 'long_titles': [],
        'missing_descriptions': [], 'duplicate_descriptions': defaultdict(list), 'short_descriptions': [], 'long_descriptions': [],
        'duplicate_content': defaultdict(list),
        'orphaned_pages': []
    }
    
    title_map, desc_map, content_map = defaultdict(list), defaultdict(list), defaultdict(list)
    
    min_title = int(settings.get('min_title_length', 10))
    max_title = int(settings.get('max_title_length', 60))
    min_desc = int(settings.get('min_desc_length', 70))
    max_desc = int(settings.get('max_desc_length', 160))

    for page in pages:
        if page.is_orphan: analysis['orphaned_pages'].append(page)

        # Title analysis
        if not page.title:
            analysis['missing_titles'].append(page)
        else:
            if len(page.title) < min_title: analysis['short_titles'].append(page)
            if len(page.title) > max_title: analysis['long_titles'].append(page)
            title_map[page.title].append(page)

        # Description analysis
        if not page.meta_description:
            analysis['missing_descriptions'].append(page)
        else:
            if len(page.meta_description) < min_desc: analysis['short_descriptions'].append(page)
            if len(page.meta_description) > max_desc: analysis['long_descriptions'].append(page)
            desc_map[page.meta_description].append(page)
            
        # Duplicate content
        if page.content_hash:
            content_map[page.content_hash].append(page)

    analysis['duplicate_titles'] = {title: page_list for title, page_list in title_map.items() if len(page_list) > 1}
    analysis['duplicate_descriptions'] = {desc: page_list for desc, page_list in desc_map.items() if len(page_list) > 1}
    analysis['duplicate_content'] = {h: page_list for h, page_list in content_map.items() if len(page_list) > 1}
    
    return analysis

def generate_csv(pages):
    # ... (this function can remain the same) ...
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(['URL', 'Status Code', 'Title', 'Meta Description', 'Is Orphan', 'Incoming Links'])
    for page in pages:
        writer.writerow([page.url, page.status_code, page.title, page.meta_description, page.is_orphan, page.incoming_links])
    return output.getvalue()