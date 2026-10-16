"""Targeted fresh collection-only reproduction; does not call analysis API/models."""
import datetime
import json
import pathlib
import traceback
from urllib.parse import urlsplit
from oss import crawler, browser_render

out=pathlib.Path(r'C:\Users\ujkio\Downloads\AI바우처 Report\수정검증_20261016') / (
    '수집기_재현_' + datetime.datetime.now().strftime('%Y%m%d_%H%M%S'))
out.mkdir(parents=True, exist_ok=False)
original=crawler._public_http_url
checks=[]
def inspected(url):
    try:
        return original(url)
    except Exception as error:
        parsed=urlsplit(url)
        checks.append({'scheme':parsed.scheme,'host':parsed.hostname,'path':parsed.path,
                       'exception':type(error).__name__,'message':str(error)})
        raise
crawler._public_http_url=inspected
browser_render._public_http_url=inspected
results=[]
for name,url in [('os2019','http://os2019.co.kr/'),('biovit','http://www.biovit.co.kr/')]:
    checks.clear();diag={};raw=[]
    def save(url,body):
        filename=f'재현_{name}_{len(raw)+1:02d}.html'
        (out/filename).write_bytes(body)
        raw.append({'url':url,'file':filename,'bytes':len(body)})
    record={'url':url,'at':datetime.datetime.now().astimezone().isoformat()}
    try:
        pages=crawler.crawl_site(url,max_pages=1,on_page=save,diagnostics=diag)
        record['result']=[{'url':p.url,'text_length':len(p.text)} for p in pages]
    except Exception as error:
        chain=[];e=error
        while e:
            chain.append({'type':type(e).__name__,'message':str(e)})
            e=e.__cause__
        record['exception_chain']=chain
        record['traceback']=traceback.format_exc()
    record.update(diagnostics=diag,failed_url_checks=checks.copy(),raw=raw)
    results.append(record)
    print(json.dumps({k:v for k,v in record.items() if k!='traceback'},ensure_ascii=False),flush=True)
(out/'수집실패_추가재현.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
