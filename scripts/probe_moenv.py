import json,os
from pathlib import Path
from datetime import datetime,timezone
from urllib.request import Request,build_opener,HTTPRedirectHandler
from urllib.parse import urlencode
from urllib.error import HTTPError

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None

def inspect_payload(payload):
    if not isinstance(payload,dict):return {'status':'unexpected_json_type'}
    box=payload.get('result',payload)
    if not isinstance(box,dict) or not isinstance(box.get('records'),list):return {'status':'records_missing'}
    rows=box['records']
    if any(not isinstance(r,dict) for r in rows):return {'status':'invalid_records'}
    total=box.get('total',payload.get('total'))
    total=int(total) if not isinstance(total,bool) and str(total).isdigit() else None
    return {'status':'ok' if rows else 'empty_records','returned_rows':len(rows),'reported_total':total,'fields':sorted({str(k) for r in rows for k in r})}

def probe(dataset,key):
    report={'dataset':dataset,'endpoint_host':'data.moenv.gov.tw','requested_rows':1}
    if not key:report['status']='missing_secret';return report
    url='https://data.moenv.gov.tw/api/v2/'+dataset.lower()+'?'+urlencode({'format':'json','offset':0,'limit':1,'api_key':key})
    try:
        with build_opener(NoRedirect()).open(Request(url,headers={'Accept':'application/json'}),timeout=60) as response:
            report['http_status']=response.status
            body=response.read(5000001)
        if len(body)>5000000:report['status']='response_too_large'
        else:
            try:report.update(inspect_payload(json.loads(body.decode('utf-8-sig'))))
            except (ValueError,UnicodeDecodeError):report['status']='invalid_json'
    except HTTPError as error:report.update({'status':'http_error','http_status':error.code})
    except Exception as error:report.update({'status':'request_failed','error_type':type(error).__name__})
    if key:report=json.loads(json.dumps(report,ensure_ascii=False).replace(key,'[REDACTED]'))
    return report

if __name__=='__main__':
    key=os.environ.get('MOENV_API_KEY','').strip()
    result={'checked_at_utc':datetime.now(timezone.utc).isoformat(),'probe_only':True,'raw_values_saved':False,'datasets':[probe(name,key) for name in ['EMS_S_01','EMS_S_07']]}
    path=Path('reports/environment/api-probe.json');path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print('Probe report saved; credentials and response values not logged')
