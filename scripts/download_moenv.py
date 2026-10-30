import hashlib,json,os,time
from pathlib import Path
from datetime import datetime,timezone
from urllib.request import Request,build_opener,HTTPRedirectHandler
from urllib.parse import urlencode
from urllib.error import HTTPError
EXPECTED={'EMS_S_01':{'emsno','wgs84lon','wgs84lat','isair','iswater','iswaste'},'EMS_S_07':{'site_id','wgs84_lat','wgs84_lng'}}
class DownloadError(ValueError):pass
class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None
class Client:
    def __init__(self,key):self.key=key;self.requests=0
    def page(self,dataset,offset,limit):
        if not self.key:raise DownloadError('missing_secret')
        url='https://data.moenv.gov.tw/api/v2/'+dataset.lower()+'?'+urlencode({'api_key':self.key,'format':'json','offset':offset,'limit':limit})
        for attempt in range(3):
            if self.requests>=250:raise DownloadError('request_safety_budget_exhausted')
            self.requests+=1
            try:
                with build_opener(NoRedirect()).open(Request(url,headers={'Accept':'application/json'}),timeout=60) as response:raw=response.read(20000001)
                if len(raw)>20000000:raise DownloadError('response_too_large')
                try:payload=json.loads(raw.decode('utf-8-sig'))
                except (ValueError,UnicodeDecodeError):raise DownloadError('invalid_json') from None
                return payload
            except HTTPError as error:
                if error.code not in (429,500,502,503,504) or attempt==2:raise DownloadError('http_'+str(error.code)) from None
            except DownloadError:raise
            except Exception:
                if attempt==2:raise DownloadError('request_failed') from None
            time.sleep(2**attempt)
        raise DownloadError('retries_exhausted')
def records(payload):
    if isinstance(payload,list):rows=payload
    elif isinstance(payload,dict):
        box=payload.get('result',payload)
        rows=box.get('records') if isinstance(box,dict) else None
    else:rows=None
    if not isinstance(rows,list) or any(not isinstance(r,dict) for r in rows):raise DownloadError('invalid_records_layout')
    return rows
def collect(dataset,fetch,limit=1000,max_pages=250):
    if dataset not in EXPECTED:raise DownloadError('unsupported_dataset')
    offset=0;allrows=[];seen=set();fields=set()
    for page in range(max_pages):
        rows=records(fetch(dataset,offset,limit))
        if len(rows)>limit:raise DownloadError('limit_not_honored')
        if not rows:
            if not allrows:raise DownloadError('unexpected_empty_dataset')
            return allrows,{'dataset':dataset,'downloaded_records':len(allrows),'successful_page_requests':page+1,'page_size':limit,'termination':'observed_empty_page','fields':sorted(fields),'status':'downloaded_to_empty_page','official_total_available':False,'national_completeness_verified':False,'snapshot_consistency':'not_guaranteed; offset pagination can change while downloading'}
        for row in rows:
            keys={str(k).lower() for k in row}
            if not EXPECTED[dataset].issubset(keys):raise DownloadError('required_fields_missing')
            fields.update(str(k) for k in row)
        digest=hashlib.sha256(json.dumps(rows,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
        if digest in seen:raise DownloadError('repeated_page')
        seen.add(digest);allrows.extend(rows);offset+=len(rows)
    raise DownloadError('page_safety_limit')
def main():
    key=os.environ.get('MOENV_API_KEY','').strip();client=Client(key)
    target=Path('environment-snapshot');target.mkdir(exist_ok=True)
    report={'started_at_utc':datetime.now(timezone.utc).isoformat(),'page_size':1000,'request_budget':250,'datasets':[],'credentials_saved':False,'live_map_changed':False}
    failed=False
    for dataset in EXPECTED:
        start=client.requests
        try:
            rows,meta=collect(dataset,client.page)
            data=json.dumps(rows,ensure_ascii=False,allow_nan=False).encode('utf-8')
            if key.encode() in data:raise DownloadError('credential_echo_detected')
            filename=dataset+'.json';(target/filename).write_bytes(data)
            meta.update({'file':filename,'sha256':hashlib.sha256(data).hexdigest(),'fields_observed':len(meta['fields'])})
        except DownloadError as error:
            meta={'dataset':dataset,'status':'failed','reason':str(error)};failed=True
        except Exception:
            meta={'dataset':dataset,'status':'failed','reason':'unexpected_processing_failure'};failed=True
        meta['actual_http_requests']=client.requests-start;report['datasets'].append(meta)
    report['finished_at_utc']=datetime.now(timezone.utc).isoformat();report['actual_http_requests']=client.requests
    report['status']='failed_or_partial' if failed else 'both_downloaded_to_empty_page'
    output=Path('reports/environment/download-quality.json');output.parent.mkdir(parents=True,exist_ok=True)
    text=json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False)
    output.write_text(text,encoding='utf-8');(target/'manifest.json').write_text(text,encoding='utf-8')
    print('Download report written; no credentials or record values logged')
    if failed:raise SystemExit(1)
if __name__=='__main__':main()
