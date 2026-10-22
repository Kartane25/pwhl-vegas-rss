#!/usr/bin/env python3
"""Create an RSS 2.0 feed from official PWHL Las Vegas news pages."""
from __future__ import annotations
import datetime as dt
import email.utils
import json
import os
import re
import time
from html import escape
from urllib.parse import urljoin, urlparse
import xml.etree.ElementTree as ET

import requests
from bs4 import BeautifulSoup

HOME = 'https://www.thepwhl.com/en/teams/las-vegas'
ARTICLE_PREFIX = '/en/teams/las-vegas/news/'
OUT = 'site/feed.xml'
LIMIT = 20
NS_CONTENT = 'http://purl.org/rss/1.0/modules/content/'
NS_MEDIA = 'http://search.yahoo.com/mrss/'
ET.register_namespace('content', NS_CONTENT)
ET.register_namespace('media', NS_MEDIA)
SESSION = requests.Session()
SESSION.headers.update({'User-Agent': 'Mozilla/5.0 (compatible; PWHLLasVegasNewsRSS/1.0; personal news reader)', 'Accept-Language':'en-US,en;q=0.9'})


def fetch(url):
    r = SESSION.get(url, timeout=25)
    r.raise_for_status()
    return BeautifulSoup(r.text, 'html.parser')


def meta(soup, *keys):
    for key in keys:
        node = soup.find('meta', attrs={'property': key}) or soup.find('meta', attrs={'name': key})
        if node and node.get('content', '').strip():
            return node['content'].strip()
    return ''


def discover(soup):
    result = []
    for a in soup.select('a[href]'):
        url = urljoin(HOME, a['href']).split('#')[0].split('?')[0]
        parsed = urlparse(url)
        if parsed.netloc not in ('thepwhl.com', 'www.thepwhl.com'):
            continue
        path = parsed.path.rstrip('/')
        # Only official Las Vegas news articles. Exclude /news index.
        if not path.startswith(ARTICLE_PREFIX) or path == ARTICLE_PREFIX.rstrip('/'):
            continue
        if url not in result:
            result.append(url)
    return result[:LIMIT]


def jsonld_articles(soup):
    objs=[]
    for tag in soup.select('script[type="application/ld+json"]'):
        try: raw=json.loads(tag.string or tag.get_text())
        except (ValueError,TypeError): continue
        stack=[raw]
        while stack:
            obj=stack.pop()
            if isinstance(obj, list): stack.extend(obj)
            elif isinstance(obj, dict):
                objs.append(obj)
                stack.extend(v for k,v in obj.items() if k in ('@graph','mainEntity','itemListElement'))
    return [o for o in objs if any(t in str(o.get('@type','')) for t in ('Article','NewsArticle'))]


def clean_text(text):
    return ' '.join((text or '').split())


def parse_article(url):
    soup = fetch(url)
    schemas=jsonld_articles(soup)
    item=schemas[0] if schemas else {}
    title=meta(soup,'og:title','twitter:title') or item.get('headline','')
    if not title and soup.h1: title=soup.h1.get_text(' ',strip=True)
    title=clean_text(title)
    description=meta(soup,'og:description','description','twitter:description') or item.get('description','')
    description=clean_text(description)
    if not description:
        main=soup.find('article') or soup.find('main')
        if main:
            for p in main.find_all('p'):
                value=clean_text(p.get_text(' ',strip=True))
                if len(value)>80:
                    description=value
                    break
    image=meta(soup,'og:image','twitter:image')
    if not image and isinstance(item.get('image'),str): image=item['image']
    if not image and isinstance(item.get('image'),dict): image=item['image'].get('url','')
    image=urljoin(url,image) if image else ''
    # Structured dates are ideal; page URL supplies fallback for official articles.
    published=item.get('datePublished') or meta(soup,'article:published_time','datePublished')
    if not published:
        m=re.search(r'/news/(\d{4})/([a-z]+)/([0-9]{1,2})/',url,re.I)
        if m:
            try: published=dt.datetime.strptime(' '.join(m.groups()),'%Y %B %d').replace(tzinfo=dt.timezone.utc).isoformat()
            except ValueError: pass
    stamp=None
    if published:
        try: stamp=dt.datetime.fromisoformat(str(published).replace('Z','+00:00'))
        except ValueError: pass
    if not stamp: stamp=dt.datetime.now(dt.timezone.utc)
    if stamp.tzinfo is None: stamp=stamp.replace(tzinfo=dt.timezone.utc)
    if not title: raise ValueError('No title extracted from '+url)
    return {'title':title,'url':url,'description':description[:750], 'image':image,'date':stamp}


def build():
    soup=fetch(HOME)
    urls=discover(soup)
    if not urls: raise RuntimeError('No official Las Vegas news links found on homepage. Website markup may have changed.')
    articles=[]
    for url in urls:
        try:
            a=parse_article(url)
            articles.append(a)
            print('OK:',a['title'][:90])
        except Exception as exc:
            print('SKIP:',url,repr(exc))
        time.sleep(0.3)
    if not articles: raise RuntimeError('No articles could be parsed; refusing to publish an empty feed.')
    articles.sort(key=lambda a:a['date'],reverse=True)
    rss=ET.Element('rss',{'version':'2.0'})
    channel=ET.SubElement(rss,'channel')
    def add(parent,name,value): ET.SubElement(parent,name).text=value or ''
    add(channel,'title','PWHL Las Vegas | Official Team News')
    add(channel,'link',HOME)
    add(channel,'description','Latest official news from PWHL Las Vegas')
    add(channel,'language','en-US')
    add(channel,'lastBuildDate',email.utils.format_datetime(dt.datetime.now(dt.timezone.utc),usegmt=True))
    for a in articles:
        entry=ET.SubElement(channel,'item')
        add(entry,'title',a['title'])
        add(entry,'link',a['url'])
        guid=ET.SubElement(entry,'guid',{'isPermaLink':'true'}); guid.text=a['url']
        add(entry,'pubDate',email.utils.format_datetime(a['date']))
        add(entry,'description',a['description'])
        body='<p>'+escape(a['description'])+'</p>' if a['description'] else ''
        if a['image']:
            ET.SubElement(entry,f'{{{NS_MEDIA}}}content',{'url':a['image'],'medium':'image'})
            body='<p><img src="'+escape(a['image'],quote=True)+'" alt="" /></p>'+body
        if body: ET.SubElement(entry,f'{{{NS_CONTENT}}}encoded').text=body
    os.makedirs(os.path.dirname(OUT),exist_ok=True)
    ET.indent(rss,space='  ')
    ET.ElementTree(rss).write(OUT,encoding='utf-8',xml_declaration=True)
    print('Wrote',OUT,'articles:',len(articles),'with images:',sum(bool(a['image']) for a in articles))

if __name__=='__main__': build()
