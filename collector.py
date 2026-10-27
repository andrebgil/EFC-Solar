#!/usr/bin/env python3
"""Recolhe concursos e noticias do sector solar em Mocambique.
Corre no GitHub Actions. Usa so a biblioteca padrao do Python.
Escreve data/concursos.json, data/noticias.json e data/status.json."""
import json, re, unicodedata, urllib.request, urllib.parse, xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from pathlib import Path

DATA = Path('data')
NOW = datetime.now(timezone.utc)
ISO = lambda d: d.isoformat(timespec='seconds')
UA = 'Mozilla/5.0 (compatible; EFCSolarBot/1.0; +https://github.com/andrebgil/EFC-Solar)'
KEEP_DAYS, MAX_AGE_DAYS = 45, 60

SOLAR = ['solar', 'fotovolt', 'photovolt', 'painel solar', 'paineis solares', 'energia renov', 'renewable',
         'mini-rede', 'mini rede', 'minirede', 'mini-grid', 'minigrid', 'off-grid', 'offgrid', 'bateria',
         'battery', 'armazenamento', 'electrific', 'eletrific', 'proler', 'get fit', 'getfit', 'faser',
         'inversor', 'inverter', 'proenergia', 'energia para todos', 'kwp', 'mwp', 'mwac']
TENDER = ['concurso', 'tender', 'procurement', 'aquisic', 'adjudic', 'manifestacao de interesse',
          'expression of interest', 'qualificacao', 'qualification', 'convite', 'rfp', 'rfq', 'eoi',
          'licitac', 'request for proposal', 'request for quotation', 'invitation to bid', 'invitation for bid',
          'consultoria', 'empreitada', 'fornecimento', 'supply of', 'call for']


def norm(s):
    s = unicodedata.normalize('NFKD', (s or '').lower())
    return ''.join(c for c in s if not unicodedata.combining(c))


def has_solar(s):
    return any(k in s for k in SOLAR) or re.search(r'\bpv\b', s) is not None


def has_tender(s):
    return any(k in s for k in TENDER)


def fetch(url, timeout=25):
    last = None
    for _ in range(2):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': UA, 'Accept-Language': 'pt,en;q=0.8'})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read(3_000_000)
                cs = r.headers.get_content_charset() or 'utf-8'
            return raw.decode(cs, errors='replace')
        except Exception as e:  # noqa
            last = e
    raise last


class LinkParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links, self.cur = [], None

    def handle_starttag(self, tag, attrs):
        if tag == 'a':
            d = dict(attrs)
            self.cur = {'href': d.get('href') or '', 'text': [], 'title': d.get('title') or ''}

    def handle_data(self, data):
        if self.cur is not None:
            self.cur['text'].append(data)

    def handle_endtag(self, tag):
        if tag == 'a' and self.cur is not None:
            self.links.append(self.cur)
            self.cur = None


def scrape(name, url, need):
    """need: 'solar' (so itens com termos solares), 'tender' (termos de concurso), 'both' (ambos)."""
    p = LinkParser()
    p.feed(fetch(url))
    out, seen = [], set()
    for l in p.links:
        title = ' '.join(''.join(l['text']).split()) or ' '.join(l['title'].split())
        href = urllib.parse.urljoin(url, l['href'].strip())
        if not href.startswith('http') or len(title) < 12 or len(title) > 300 or href in seen:
            continue
        n = norm(title + ' ' + urllib.parse.unquote(urllib.parse.urlparse(href).path))
        s, t = has_solar(n), has_tender(n)
        if (need == 'solar' and not s) or (need == 'tender' and not t) or (need == 'both' and not (s and t)):
            continue
        seen.add(href)
        out.append({'title': title, 'url': href, 'source': name, 'date': None, 'rel': 1 if s else 0})
        if len(out) >= 60:
            break
    return out


def worldbank(name):
    url = 'https://search.worldbank.org/api/v2/procnotices?format=json&rows=100&countrycode_exact=MZ&srt=noticedate&order=desc'
    j = json.loads(fetch(url))
    rows = j.get('procnotices') or {}
    rows = rows.values() if isinstance(rows, dict) else rows
    out = []
    for d in rows:
        title = d.get('bid_description') or d.get('project_name') or ''
        if not title or not has_solar(norm(title + ' ' + str(d.get('project_name', '')))):
            continue
        nid = d.get('id')
        link = ('https://projects.worldbank.org/en/projects-operations/procurement-detail/' + str(nid)) if nid else \
            'https://projects.worldbank.org/en/projects-operations/procurement?countrycode_exact=MZ'
        out.append({'title': title.strip(), 'url': link, 'source': name, 'date': (d.get('noticedate') or '')[:10] or None, 'rel': 1})
    return out


def gnews(q, lang='pt'):
    ce = 'MZ:pt-PT' if lang == 'pt' else 'MZ:en'
    url = ('https://news.google.com/rss/search?q=' + urllib.parse.quote(q + ' when:%dd' % MAX_AGE_DAYS) +
           '&hl=%s&gl=MZ&ceid=%s' % ('pt-PT' if lang == 'pt' else 'en', ce))
    root = ET.fromstring(fetch(url))
    out = []
    for it in root.iter('item'):
        title = (it.findtext('title') or '').strip()
        link = (it.findtext('link') or '').strip()
        src = (it.findtext('source') or '').strip() or 'Google Notícias'
        try:
            d = parsedate_to_datetime(it.findtext('pubDate'))
            if d.tzinfo is None:
                d = d.replace(tzinfo=timezone.utc)
        except Exception:  # noqa
            d = None
        if d and NOW - d > timedelta(days=MAX_AGE_DAYS):
            continue
        if src and title.endswith(' - ' + src):
            title = title[: -len(src) - 3]
        if title and link:
            out.append({'title': title, 'url': link, 'source': src, 'date': ISO(d)[:10] if d else None})
    return out


# ---------------------------------------------------------------- fontes
PORTALS = [  # so ficam itens com termos solares
    ('Concursos.co.mz', 'https://concursos.co.mz/'),
    ('Mozconnections', 'https://concursos.mozconnections.co.mz/'),
    ('ts.gov.mz', 'https://ts.gov.mz/'),
    ('Mozambique Tenders', 'https://www.mozambiquetenders.com/'),
    ('MozBids', 'https://mozbids.com/'),
    ('Gugla', 'https://gugla.co.mz/'),
    ('TendersInfo', 'https://www.tendersinfo.com/'),
    ('OnlineTenders', 'https://www.onlinetenders.co.za/'),
    ('BidDetail', 'https://www.biddetail.com/'),
    ('Portal Fornecedores ENH', 'https://pfornecedores.enh.co.mz/'),
    ('ANE', 'https://www.ane.gov.mz/'),
    ('UNDP Moçambique', 'https://www.undp.org/mozambique/compras'),
    ('DevelopmentAid', 'https://www.developmentaid.org/tenders'),
    ('UNGM (ONU)', 'https://www.ungm.org/Public/Notice'),
    ('TotalEnergies MZ LNG', 'https://mzlng.totalenergies.co.mz/'),
    ('Vulcan International', 'https://www.vulcaninternational.com/'),
    ('Kenmare Resources', 'https://www.kenmareresources.com/'),
    ('BAD (AfDB) aquisições', 'https://www.afdb.org/en/projects-and-operations/procurement'),
]
ENTITIES = [  # basta termo de concurso; 'rel' diz se e solar
    ('ARENE', 'https://www.arene.org.mz/'),
    ('MIREME', 'https://mireme.gov.mz/'),
    ('FUNAE', 'https://www.funae.co.mz/'),
    ('EDM', 'https://www.edm.co.mz/'),
    ('UFSA', 'https://www.ufsa.gov.mz/'),
    ('CEDSIF', 'https://www.cedsif.gov.mz/'),
    ('FNDS', 'https://www.fnds.gov.mz/'),
    ('Enabel Moçambique', 'https://www.enabel.be/country/mozambique/'),
]
NAMES = ['ARENE', 'MIREME', 'FUNAE', 'EDM', 'PROLER', 'GET FiT', 'FASER', 'Enabel', 'GIZ', 'UFSA', 'UNDP',
         'CEDSIF', 'FNDS', 'PTUM Projeto de Transformação Urbana de Maputo', 'AMER Associação Moçambicana de Energias Renováveis',
         'Conselho Municipal de Maputo', 'Município da Matola', 'Município de Marracuene', 'embaixada Maputo',
         'Nações Unidas Maputo', 'ONG Maputo']
TENDER_Q = ['concursos maputo', 'concursos mocambique', 'concursos solar maputo', 'concursos solar mocambique',
            'concursos fotovoltaicos maputo', 'concursos fotovoltaicos mocambique',
            'concursos em maputo a base de energia solar', 'concursos em mocambique a base de energia solar',
            'mini-redes solares concurso Moçambique', 'pré-qualificação energia solar Moçambique'] + \
           ['concurso ' + n for n in NAMES]
TENDER_Q_EN = ['tender solar Mozambique', 'tender solar Maputo', 'expression of interest solar Mozambique',
               'request for proposals solar Maputo', 'procurement photovoltaic Mozambique', 'mini-grid tender Mozambique']
NEWS_Q = ['energia solar Moçambique', 'fotovoltaico Moçambique', 'energias renováveis Moçambique',
          'mini-redes solares Moçambique', 'EDM energia solar', 'FUNAE energia', 'ARENE energia renovável']
NEWS_Q_EN = ['Mozambique solar energy', 'Mozambique renewable energy', 'Mozambique solar tender']


def run_source(job):
    kind, name, args = job
    try:
        if kind == 'scrape':
            return name, 'tender', scrape(name, *args), None
        if kind == 'wb':
            return name, 'tender', worldbank(name), None
        if kind == 'gt':
            items = [i for i in gnews(*args) if has_tender(norm(i['title']))]
            for i in items:
                i['rel'] = 1 if has_solar(norm(i['title'])) else 0
            return name, 'tender', items, None
        if kind == 'gn':
            items = [i for i in gnews(*args) if has_solar(norm(i['title'])) or 'energia' in norm(i['title'])]
            return name, 'news', items, None
    except Exception as e:  # noqa
        return name, 'tender' if kind != 'gn' else 'news', [], '%s: %s' % (type(e).__name__, str(e)[:120])


def merge(path, new_items):
    old, first_run = {}, not path.exists()
    if not first_run:
        try:
            old = {i['url']: i for i in json.loads(path.read_text('utf-8')).get('items', [])}
        except Exception:  # noqa
            first_run = True
    cur = {}
    for it in new_items:
        prev = old.get(it['url'])
        if prev:
            it['first_seen'] = prev['first_seen']
        elif first_run:  # 1a execucao: nao marcar tudo como "novo"
            it['first_seen'] = (it.get('date') or ISO(NOW - timedelta(days=7))[:10]) + 'T00:00:00+00:00'
        else:
            it['first_seen'] = ISO(NOW)
        it['last_seen'] = ISO(NOW)
        cur[it['url']] = it
    cutoff = NOW - timedelta(days=KEEP_DAYS)
    for u, p in old.items():
        try:
            if u not in cur and datetime.fromisoformat(p['last_seen']) >= cutoff:
                cur[u] = p
        except Exception:  # noqa
            pass
    return sorted(cur.values(), key=lambda i: i.get('first_seen', ''), reverse=True)


def main():
    DATA.mkdir(exist_ok=True)
    jobs = [('scrape', n, (u, 'solar')) for n, u in PORTALS] + [('scrape', n, (u, 'tender')) for n, u in ENTITIES]
    jobs += [('wb', 'Banco Mundial (API)', ())]
    jobs += [('gt', 'Google: ' + q, (q, 'pt')) for q in TENDER_Q] + [('gt', 'Google: ' + q, (q, 'en')) for q in TENDER_Q_EN]
    jobs += [('gn', 'Google: ' + q, (q, 'pt')) for q in NEWS_Q] + [('gn', 'Google: ' + q, (q, 'en')) for q in NEWS_Q_EN]
    with ThreadPoolExecutor(8) as ex:
        results = list(ex.map(run_source, jobs))
    tenders, news, status, g = [], [], [], {'ok': 0, 'fail': 0, 'n': 0}
    for name, kind, items, err in results:
        (tenders if kind == 'tender' else news).extend(items)
        if name.startswith('Google:'):
            g['fail' if err else 'ok'] += 1
            g['n'] += len(items)
        else:
            status.append({'name': name, 'ok': err is None, 'n': len(items), 'err': err})
    status.append({'name': 'Pesquisas Google (%d consultas)' % (g['ok'] + g['fail']), 'ok': g['fail'] == 0,
                   'n': g['n'], 'err': ('%d consulta(s) falharam' % g['fail']) if g['fail'] else None})
    def dedupe(items):  # o mesmo concurso aparece em varias fontes: fica o primeiro
        seen, out = set(), []
        for it in items:
            k = re.sub(r'[^a-z0-9]+', ' ', norm(it['title']))[:90]
            if k not in seen:
                seen.add(k)
                out.append(it)
        return out
    tenders, news = dedupe(tenders), dedupe(news)
    for it in tenders + news:
        it['title'] = it['title'][:300]
    (DATA / 'concursos.json').write_text(json.dumps({'updated': ISO(NOW), 'items': merge(DATA / 'concursos.json', tenders)}, ensure_ascii=False, indent=1), 'utf-8')
    (DATA / 'noticias.json').write_text(json.dumps({'updated': ISO(NOW), 'items': merge(DATA / 'noticias.json', news)[:80]}, ensure_ascii=False, indent=1), 'utf-8')
    (DATA / 'status.json').write_text(json.dumps({'updated': ISO(NOW), 'sources': status}, ensure_ascii=False, indent=1), 'utf-8')
    print('concursos:', len(tenders), 'noticias:', len(news), 'fontes com erro:', sum(1 for s in status if not s['ok']))


if __name__ == '__main__':
    main()
