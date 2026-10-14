import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from generate import quote_from_payload, parse_news_entry, build_data, render
import pytest

def sample(now, price=100, previous=90):
    return {'chart':{'result':[{'meta':{'regularMarketPrice':price,'chartPreviousClose':previous,'regularMarketTime':int(now.timestamp())}}]}}

def test_valid_quote():
    now = datetime(2026,10,14,7,30,tzinfo=ZoneInfo('America/Sao_Paulo'))
    q=quote_from_payload('Teste','T','pontos','https://example.org',sample(now),now)
    assert q['delta']=='+11,11%'

def test_invalid_quote():
    now=datetime(2026,10,14,7,30,tzinfo=ZoneInfo('America/Sao_Paulo'))
    with pytest.raises(ValueError):
        quote_from_payload('Teste','T','pontos','https://example.org',sample(now,0,90),now)
    with pytest.raises(ValueError):
        quote_from_payload('Teste','T','pontos','https://example.org',sample(now-timedelta(days=6)),now)

def test_stale_news():
    import time
    now=datetime(2026,10,14,7,30,tzinfo=ZoneInfo('America/Sao_Paulo'))
    entry={'title':'Teste de notícia bastante grande', 'link':'https://example.org',
           'published_parsed':time.gmtime((now-timedelta(days=3)).timestamp())}
    assert parse_news_entry(entry,'Brasil',now) is None

def test_render_escaped(tmp_path):
    now=datetime(2026,10,14,7,30,tzinfo=ZoneInfo('America/Sao_Paulo'))
    quote={'status':'Indisponível','label':'Teste','url':'https://example.org','value':'—','delta':'—','direction':'flat','observed':'Não validada'}
    data=build_data(now,[quote]*6,[],[])
    data['lead']={'title':'<script>alert(1)</script>','url':'https://example.org','source':'Teste','when':'07:30'}
    render(data,tmp_path/'index.html')
    assert '&lt;script&gt;' in (tmp_path/'index.html').read_text()
