"""Morning Call: coleta segura, renderização e publicação estática."""
import argparse
import hashlib
import json
import logging
import math
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote, urlparse
from zoneinfo import ZoneInfo

import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
import requests
from jinja2 import Environment, FileSystemLoader, select_autoescape

ROOT = Path(__file__).resolve().parents[1]
TZ = ZoneInfo('America/Sao_Paulo')
HEADERS = {'User-Agent': 'MorningCallResearch/1.0 (contact: site administrator)', 'Accept': 'application/json, application/xml, text/xml, */*'}
SYMBOLS = [
    ('Ibovespa', '^BVSP', 'pontos', 'https://finance.yahoo.com/quote/%5EBVSP/'),
    ('USD/BRL', 'BRL=X', 'BRL', 'https://finance.yahoo.com/quote/BRL=X/'),
    ('S&P 500', '^GSPC', 'pontos', 'https://finance.yahoo.com/quote/%5EGSPC/'),
    ('Nasdaq Composite', '^IXIC', 'pontos', 'https://finance.yahoo.com/quote/%5EIXIC/'),
    ('Brent (futuro)', 'BZ=F', 'USD', 'https://finance.yahoo.com/quote/BZ=F/'),
    ('US Treasury 10Y', '^TNX', '%', 'https://finance.yahoo.com/quote/%5ETNX/'),
]
QUERIES = [
    ('Brasil · Mercados', 'Ibovespa dólar Selic mercado financeiro when:1d', 'pt-BR', 'BR', 'BR:pt-419'),
    ('Macro · Brasil', 'Banco Central Copom inflação PIB economia when:1d', 'pt-BR', 'BR', 'BR:pt-419'),
    ('Global · Mercados', 'Federal Reserve Wall Street inflation markets when:1d', 'en-US', 'US', 'US:en'),
    ('Commodities', 'oil Brent iron ore commodities market when:1d', 'en-US', 'US', 'US:en'),
]


def now_local():
    return datetime.now(TZ)


def safe_json(path, fallback):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (FileNotFoundError, ValueError):
        return fallback


def iso_to_dt(ts):
    return datetime.fromtimestamp(int(ts), timezone.utc).astimezone(TZ)


def quote_from_payload(label, symbol, unit, source_url, payload, now):
    """Rejeita preços inválidos, variação inconsistente e observações futuras/antigas."""
    result = payload['chart']['result'][0]
    meta = result['meta']
    price = float(meta['regularMarketPrice'])
    previous = float(meta['chartPreviousClose']) if meta.get('chartPreviousClose') else float(meta['previousClose'])
    ts = int(meta.get('regularMarketTime') or 0)
    if not (math.isfinite(price) and math.isfinite(previous) and 0 < price < 1e8 and 0 < previous < 1e8):
        raise ValueError('valor inválido')
    observed = iso_to_dt(ts)
    age = now - observed
    if age < timedelta(minutes=-10) or age > timedelta(days=5):
        raise ValueError('cotação fora da janela de 5 dias')
    delta = (price / previous - 1) * 100
    if abs(delta) > 35:  # bloqueia anomalias grandes; pode exigir revisão manual em eventos extremos
        raise ValueError('variação anômala >35%')
    return dict(label=label, value=format_value(price, unit), delta=f'{delta:+.2f}%'.replace('.', ','),
                direction='up' if delta > 0 else ('down' if delta < 0 else 'flat'),
                observed=observed.strftime('%d/%m/%Y %H:%M BRT'), source='Yahoo Finance (endpoint não oficial)',
                url=source_url, status='Última observação', symbol=symbol)


def format_value(price, unit):
    decimals = 4 if unit == 'BRL' else (2 if unit in ('USD', '%') else 0)
    formatted = f'{price:,.{decimals}f}'.replace(',', 'X').replace('.', ',').replace('X', '.')
    return ('R$ ' if unit == 'BRL' else 'US$ ' if unit == 'USD' else '') + formatted + ('%' if unit == '%' else '')


def get_quotes(now, fixture=None):
    quotes = []
    for label, symbol, unit, url in SYMBOLS:
        try:
            if fixture is not None:
                payload = fixture[symbol]
            else:
                endpoint = f'https://query1.finance.yahoo.com/v8/finance/chart/{quote(symbol, safe="")}'
                response = requests.get(endpoint, params={'range':'5d','interval':'1d'}, headers=HEADERS, timeout=13)
                response.raise_for_status()
                payload = response.json()
            quotes.append(quote_from_payload(label, symbol, unit, url, payload, now))
        except (KeyError, ValueError, TypeError, IndexError, requests.RequestException) as exc:
            logging.warning('Cotação indisponível para %s: %s', symbol, exc)
            quotes.append(dict(label=label, value='Indisponível', delta='—', direction='flat',
                               observed='Não validada', source='Nenhuma cotação exibida', url=url, status='Indisponível', symbol=symbol))
    return quotes


def parse_news_entry(entry, category, now):
    parsed = entry.get('published_parsed')
    if not parsed:
        return None
    if isinstance(parsed, str):
        pub = parsedate_to_datetime(parsed).astimezone(TZ)
    else:
        from calendar import timegm
        pub = datetime.fromtimestamp(timegm(parsed), timezone.utc).astimezone(TZ)
    if pub > now + timedelta(minutes=10) or pub < now - timedelta(hours=30):
        return None
    title = re.sub(r'\s+', ' ', re.sub('<[^>]+>', '', entry.get('title', ''))).strip()
    if len(title) < 15 or len(title) > 260:
        return None
    link = entry.get('link', '')
    if urlparse(link).scheme != 'https':
        return None
    origin = entry.get('source', {})
    source = origin.get('title', '') if isinstance(origin, dict) else getattr(origin, 'title', '')
    if not source and ' - ' in title:
        source = title.rsplit(' - ', 1)[-1]
    if ' - ' in title and title.rsplit(' - ', 1)[-1].casefold() == source.casefold():
        title = title.rsplit(' - ', 1)[0]
    return dict(title=title, category=category, source=source or 'Google Notícias (agregador)',
                url=link, published=pub.isoformat(), when=pub.strftime('%d/%m %H:%M'),
                summary='Manchete publicada pela fonte indicada. Consulte a reportagem para verificar o contexto completo.',
                impact='Leitura de mercado não inferida automaticamente; verifique os dados e a matéria original.',
                tone='misto')


def get_news(now, fixture=None):
    selected, seen = [], set()
    for category, query, hl, gl, ceid in QUERIES:
        try:
            if fixture is None:
                response = requests.get('https://news.google.com/rss/search',
                                        params={'q':query,'hl':hl,'gl':gl,'ceid':ceid},
                                        headers=HEADERS, timeout=18)
                response.raise_for_status()
                xml_root = ET.fromstring(response.content)
                entries = []
                for item in xml_root.findall('.//channel/item'):
                    origin = item.find('source')
                    entries.append({'title':item.findtext('title', ''), 'link':item.findtext('link', ''),
                                    'published_parsed':item.findtext('pubDate', ''),
                                    'source':{'title':origin.text if origin is not None and origin.text else ''}})
            else:
                entries = fixture.get(category, [])
            added = 0
            for entry in entries:
                news = parse_news_entry(entry, category, now)
                if not news:
                    continue
                key = re.sub(r'[^\w]', '', news['title'].casefold())[:90]
                if key in seen:
                    continue
                seen.add(key)
                selected.append(news)
                added += 1
                if added == 3:
                    break
        except (requests.RequestException, ET.ParseError, ValueError) as exc:
            logging.warning('Feed falhou %s: %s', category, exc)
    selected.sort(key=lambda item:item['published'], reverse=True)
    return selected[:10]


def get_events(now):
    """Apenas eventos previamente cadastrados com URL de fonte oficial e fuso horário explícito."""
    events = []
    for item in safe_json(ROOT / 'config' / 'events.json', []):
        try:
            dt = datetime.fromisoformat(item['datetime'])
            if not dt.tzinfo or dt.astimezone(TZ).date() != now.date():
                continue
            if urlparse(item['source_url']).scheme != 'https':
                continue
            events.append(dict(time=dt.astimezone(TZ).strftime('%H:%M'), region=item['region'],
                               title=item['title'], url=item['source_url'], relevance=item['relevance']))
        except (ValueError, KeyError, TypeError):
            continue
    return sorted(events, key=lambda x:x['time'])


def build_data(now, quotes, news, events):
    available = sum(q['status'] != 'Indisponível' for q in quotes)
    lead = news[0] if news else None
    return dict(date_iso=now.strftime('%Y-%m-%d'), date_label=now.strftime('%d/%m/%Y'),
                run_time=now.strftime('%d/%m/%Y às %H:%M BRT'),
                generated_at=now.isoformat(), lead=lead, news=news, quotes=quotes,
                events=events, available=available, total=len(quotes),
                complete=bool(news) and available >= 3, edition='Pré-mercado' if now.hour < 10 else 'Atualização de mercado')


def render(data, output):
    env = Environment(loader=FileSystemLoader(str(ROOT / 'templates')),
                      autoescape=True, trim_blocks=True, lstrip_blocks=True)
    html = env.get_template('index.html.j2').render(**data)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(html, encoding='utf-8')


def generate(now=None, fixture=None, output=None):
    now = now or now_local()
    quotes = get_quotes(now, fixture.get('quotes') if fixture else None)
    news = get_news(now, fixture.get('news') if fixture else None)
    events = get_events(now)
    data = build_data(now, quotes, news, events)
    if output:
        render(data, Path(output))
        return data
    if not data['complete']:
        raise RuntimeError(f'Qualidade insuficiente: {data["available"]}/6 cotações; {len(news)} notícias. Edição anterior preservada.')
    site = ROOT / 'site'
    archive = ROOT / 'archive'
    archive.mkdir(parents=True, exist_ok=True)
    issue_file = archive / f'{data["date_iso"]}.json'
    issue_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    history = sorted(archive.glob('????-??-??.json'), reverse=True)
    editions = []
    for path in history:
        item = safe_json(path, {})
        if item.get('date_iso'):
            editions.append({'date':item['date_label'], 'path':f'editions/{path.stem}.html'})
    data['history'] = editions[:60]
    render(data, site / 'index.html')
    render({**data, 'history_root':True}, site / 'editions' / f'{data["date_iso"]}.html')
    # Recria histórico até 60 edições, com HTML específico de cada data.
    for path in history[:60]:
        item = safe_json(path, {})
        item['history'] = editions[:60]
        item['history_root'] = True
        if item.get('date_iso'):
            render(item, site / 'editions' / f'{path.stem}.html')
    (site / '.nojekyll').touch()
    (site / 'status.json').write_text(json.dumps({'last_update':data['generated_at'], 'quality':f'{data["available"]}/{data["total"]}', 'news':len(news)}, ensure_ascii=False), encoding='utf-8')
    return data


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--preview', action='store_true', help='Gera preview com dados reais, inclusive incompletos')
    parser.add_argument('--demo', action='store_true', help='Gera preview rotulado com dados fictícios')
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    now = now_local()
    if args.demo:
        sample = {'chart':{'result':[{'meta':{'regularMarketPrice':100.0, 'chartPreviousClose':99.0, 'regularMarketTime':int(now.timestamp())}}]}}
        from time import gmtime
        from calendar import timegm
        entry = {'title':'Exemplo ilustrativo: notícia simulada para testar o layout - Fonte fictícia',
                 'published_parsed':gmtime(now.timestamp()), 'link':'https://example.org/exemplo', 'source':{'title':'Fonte fictícia'}}
        fixture = {'quotes':{x[1]:sample for x in SYMBOLS}, 'news':{x[0]:[entry] for x in QUERIES}}
        data = generate(now=now, fixture=fixture, output=ROOT / 'site' / 'preview.html')
        demo_path=ROOT / 'site' / 'preview.html'
        demo_path.write_text(demo_path.read_text(encoding='utf-8').replace('<body>', '<body><div style="padding:18px;background:#8b1a1a;color:white;text-align:center;font-weight:bold">DEMONSTRAÇÃO · DADOS FICTÍCIOS · NÃO UTILIZAR PARA DECISÕES</div>',1), encoding='utf-8')
        print('PREVIEW DEMONSTRATIVO (NÃO PUBLICAR)', data['available'], len(data['news']))
    elif args.preview:
        data = generate(now=now, output=ROOT / 'site' / 'preview.html')
        print('PREVIEW REAL, POSSIVELMENTE INCOMPLETO', data['available'], len(data['news']))
    else:
        data = generate(now=now)
        print('PUBLICADO', data['date_iso'], data['available'], len(data['news']))


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        logging.error('%s', exc)
        sys.exit(1)
