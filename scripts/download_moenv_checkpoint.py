import hashlib,json,os
from datetime import datetime,timezone
from pathlib import Path
from urllib.request import Request,build_opener
from urllib.parse import urlencode
from download_moenv import EXPECTED,NoRedirect,records
LIMIT=1000
BUDGET=20
class SafeError(ValueError):pass
def save(path,obj):
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix(path.suffix+'.tmp')
    temp.write_text(json.dumps(obj,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8');temp.replace(path)
def fresh():return {'version':1,'datasets':{d:{'pages':[],'next_offset':0,'complete':False} for d in EXPECTED}}
def load(root):
    path=root/'checkpoint.json'
    if not path.exists():return fresh()
    state=json.loads(path.read_text(encoding='utf-8'))
    if state.get('version')!=1 or set(state.get('datasets',{}))!=set(EXPECTED):raise SafeError('checkpoint_schema_mismatch')
    for dataset,entry in state['datasets'].items():
        offset=0;digests=set()
        if not isinstance(entry.get('complete'),bool):raise SafeError('invalid_completion_flag')
        for page in entry['pages']:
            expected=dataset+'/'+str(offset)+'.json'
            if page['offset']!=offset or page['file']!=expected:raise SafeError('invalid_checkpoint_path_or_offset')
            data=(root/expected).read_bytes();rows=records(json.loads(data))
            digest=hashlib.sha256(data).hexdigest()
            if digest!=page['sha256'] or digest in digests or not 0<len(rows)<=LIMIT or len(rows)!=page['count']:raise SafeError('checkpoint_integrity_failed')
            digests.add(digest);offset+=len(rows)
        if entry['next_offset']!=offset:raise SafeError('checkpoint_offset_mismatch')
    return state
def fetch(dataset,offset,key):
    if not key:raise SafeError('missing_secret')
    url='https://data.moenv.gov.tw/api/v2/'+dataset.lower()+'?'+urlencode({'api_key':key,'format':'json','offset':offset,'limit':LIMIT})
    try:
        with build_opener(NoRedirect()).open(Request(url,headers={'Accept':'application/json'}),timeout=45) as response:data=response.read(20000001)
    except Exception:raise SafeError('http_or_network_failure') from None
    if len(data)>20000000:raise SafeError('response_too_large')
    try:return records(json.loads(data.decode('utf-8-sig')))
    except Exception:raise SafeError('invalid_response_layout') from None
def advance(root,state,dataset,request,key,budget=BUDGET):
    entry=state['datasets'][dataset];used=0;reason=None
    seen={p['sha256'] for p in entry['pages']}
    while not entry['complete'] and used<budget:
        offset=entry['next_offset'];used+=1
        try:
            rows=request(dataset,offset,key)
            if not isinstance(rows,list) or any(not isinstance(r,dict) for r in rows):raise SafeError('invalid_rows')
            if len(rows)>LIMIT:raise SafeError('limit_not_honored')
            if not rows:
                if not entry['pages']:raise SafeError('unexpected_empty_dataset')
                entry['complete']=True;entry['termination']='observed_empty_page';save(root/'checkpoint.json',state);break
            if any(not EXPECTED[dataset].issubset({str(k).lower() for k in r}) for r in rows):raise SafeError('required_fields_missing')
            data=json.dumps(rows,ensure_ascii=False,sort_keys=True,allow_nan=False).encode('utf-8')
            if key and key.encode() in data:raise SafeError('credential_echo_detected')
            digest=hashlib.sha256(data).hexdigest()
            if digest in seen:raise SafeError('repeated_page')
            relative=dataset+'/'+str(offset)+'.json';path=root/relative;path.parent.mkdir(parents=True,exist_ok=True)
            tmp=path.with_suffix('.tmp');tmp.write_bytes(data);tmp.replace(path)
            entry['pages'].append({'offset':offset,'count':len(rows),'file':relative,'sha256':digest})
            entry['next_offset']+=len(rows);seen.add(digest);save(root/'checkpoint.json',state)
        except SafeError as error:reason=str(error);break
        except Exception:reason='processing_or_storage_failure';break
    entry['last_error']=reason;save(root/'checkpoint.json',state)
    return {'dataset':dataset,'actual_http_requests':used,'saved_records':entry['next_offset'],'saved_pages':len(entry['pages']),'next_offset':entry['next_offset'],'status':'complete_to_empty_page' if entry['complete'] else ('failed' if reason else 'paused_with_checkpoint'),'reason':reason,'national_completeness_verified':False,'snapshot_consistency_verified':False}
def main():
    root=Path('environment-snapshot');root.mkdir(exist_ok=True)
    report={'checked_at_utc':datetime.now(timezone.utc).isoformat(),'request_budget_per_dataset':BUDGET,'page_size':LIMIT,'automatic_retries':False,'credentials_saved':False,'live_map_changed':False,'datasets':[]}
    try:
        state=load(root);key=os.environ.get('MOENV_API_KEY','').strip()
        for dataset in EXPECTED:report['datasets'].append(advance(root,state,dataset,fetch,key))
        report['status']='failed_or_partial' if any(d['status']=='failed' for d in report['datasets']) else ('complete_to_empty_page' if all(d['status']=='complete_to_empty_page' for d in report['datasets']) else 'paused_with_checkpoint')
    except Exception:report['status']='checkpoint_validation_failed'
    report['actual_http_requests']=sum(d['actual_http_requests'] for d in report['datasets'])
    save(Path('reports/environment/download-quality.json'),report)
    print(json.dumps(report,ensure_ascii=False))
    if report['status'] in ('failed_or_partial','checkpoint_validation_failed'):raise SystemExit(1)
if __name__=='__main__':main()
