import argparse,calendar,gzip,hashlib,json,os,re,time,unicodedata
from collections import Counter
from datetime import date,datetime,timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode,quote,quote_plus
from urllib.request import Request,build_opener
from download_moenv import NoRedirect,records
ROOT=Path('pollution-history');OUT=Path('reports/pollution-history')
SOURCES=('AQX_P_547','AQX_P_13','AQX_P_15');HOURS=tuple('monitorvalue'+str(h).zfill(2) for h in range(24))
def save(path,obj):
    path.parent.mkdir(parents=True,exist_ok=True);tmp=path.with_suffix(path.suffix+'.tmp')
    tmp.write_text(json.dumps(obj,ensure_ascii=False,separators=(',',':'),allow_nan=False),encoding='utf-8');tmp.replace(path)
def parse_date(value):
    s=unicodedata.normalize('NFKC',str(value or '')).strip().lstrip('feff')
    m=re.match(r'^(\d{4})[-/年](\d{1,2})[-/月](\d{1,2})(?:日|T| |$)',s)
    if not m:m=re.fullmatch(r'(\d{4})(\d{2})(\d{2})',s)
    if not m:return None
    try:return date(*map(int,m.groups()))
    except ValueError:return None
def inspect(rows,month=None):
    wanted=month.replace('_','-') if month else None;counts=Counter();examples=[];schema=True
    for r in rows:
        raw=str(r.get('monitordate') or '');d=parse_date(raw)
        if len(examples)<5 and raw not in [x['raw_date'] for x in examples]:examples.append({'raw_date':raw[:64],'parsed_date':d.isoformat() if d else None})
        counts['rows']+=1
        if not raw:counts['missing_date']+=1
        elif d is None:counts['unrecognized_date_format']+=1
        elif wanted and d.strftime('%Y-%m')!=wanted:counts['wrong_month']+=1
        else:counts['date_matches']+=1
        if not set(HOURS).issubset(r) or not r.get('sitename') or not r.get('itemname'):schema=False
    ok=bool(rows) and schema and not any(counts[k] for k in ('missing_date','unrecognized_date_format','wrong_month'))
    return {'status':'verified_month_sample' if ok and month else ('latest_sample_received' if ok else 'not_verified'),'counts':dict(counts),'date_examples':examples,'hourly_schema_verified':schema,'matches_requested_month':ok if month else None}
class FetchError(ValueError):pass
class Client:
    def __init__(self,key):self.key=key;self.calls=0;self.start=time.monotonic();self.last=0
    def get(self,dataset,month=None,offset=0,limit=5):
        if dataset not in SOURCES:raise FetchError('unapproved_source')
        if not self.key:raise FetchError('missing_secret')
        if self.calls>=3000 or time.monotonic()-self.start>6300:raise FetchError('pause_safety_limit')
        time.sleep(max(0,1-(time.monotonic()-self.last)))
        params={'api_key':self.key,'format':'json','offset':offset,'limit':limit}
        if month:params['year_month']=month
        self.calls+=1;self.last=time.monotonic()
        try:
            url='https://data.moenv.gov.tw/api/v2/'+dataset.lower()+'?'+urlencode(params)
            with build_opener(NoRedirect()).open(Request(url,headers={'Accept':'application/json'}),timeout=40) as response:body=response.read(20000001)
        except HTTPError as error:raise FetchError('http_'+str(error.code)) from None
        except Exception as error:raise FetchError('transport_'+type(error).__name__) from None
        if len(body)>20000000:raise FetchError('response_too_large')
        if any(v.encode() in body for v in (self.key,quote(self.key,safe=''),quote_plus(self.key))):raise FetchError('credential_echo_rejected')
        try:rows=records(json.loads(body.decode('utf-8-sig')))
        except Exception:raise FetchError('invalid_json_or_records') from None
        if len(rows)>limit:raise FetchError('limit_not_honored')
        normalized=[]
        for r in rows:
            item={str(k).lower():v for k,v in r.items()}
            if len(item)!=len(r):raise FetchError('field_collision')
            normalized.append(item)
        if self.key in json.dumps(normalized,ensure_ascii=False):raise FetchError('credential_echo_rejected')
        return normalized
def checkpoint(source):return {'version':1,'source':source,'year':2024,'months':{f'2024_{m:02d}':{'pages':[],'next_offset':0,'complete':False} for m in range(1,13)}}
def load_state():
    path=ROOT/'checkpoint.json'
    if not path.exists():return None
    state=json.loads(path.read_text(encoding='utf-8'))
    if state.get('version')!=1 or state.get('year')!=2024 or state.get('source') not in SOURCES:raise FetchError('checkpoint_schema_mismatch')
    if set(state['months'])!={f'2024_{m:02d}' for m in range(1,13)}:raise FetchError('checkpoint_months_mismatch')
    for month,entry in state['months'].items():
        offset=0;seen=set()
        for p in entry['pages']:
            name=month+'/'+str(offset)+'.json.gz'
            if p['file']!=name or p['offset']!=offset:raise FetchError('checkpoint_path_mismatch')
            raw=gzip.decompress((ROOT/name).read_bytes())
            if hashlib.sha256(raw).hexdigest()!=p['sha256'] or p['sha256'] in seen:raise FetchError('checkpoint_hash_mismatch')
            rows=json.loads(raw)
            if len(rows)!=p['rows'] or not inspect(rows,month)['matches_requested_month']:raise FetchError('checkpoint_data_mismatch')
            seen.add(p['sha256']);offset+=len(rows)
        if offset!=entry['next_offset']:raise FetchError('checkpoint_offset_mismatch')
        if not isinstance(entry.get('complete'),bool):raise FetchError('checkpoint_completion_mismatch')
        if entry['complete'] and (not entry['pages'] or entry.get('termination')!='observed_empty_page'):raise FetchError('checkpoint_termination_mismatch')
    return state
def run():
    ROOT.mkdir(exist_ok=True);OUT.mkdir(parents=True,exist_ok=True);client=Client(os.environ.get('MOENV_API_KEY','').strip())
    report={'status':'started','checked_at_utc':datetime.now(timezone.utc).isoformat(),'target_year':2024,'full_year_downloaded':False,'annual_concentrations_computed':False,'site_changed':False,'automatic_retries':False,'request_safety_limit':3000,'wall_time_safety_seconds':6300,'minimum_request_interval_seconds':1,'snapshot_consistency_verified':False,'quality_flags_interpreted':False,'actions_run_url':'https://github.com/'+os.environ.get('GITHUB_REPOSITORY','')+'/actions/runs/'+os.environ.get('GITHUB_RUN_ID','')}
    diagnostics=[];phase='checkpoint_validation';state=None
    try:
        state=load_state()
        if state is None:
            phase='source_diagnosis';chosen=None
            for source in SOURCES:
                source_ok=True
                for month in (None,'2024_01','2024_07','2024_12'):
                    try:
                        rows=client.get(source,month);finding=inspect(rows,month);finding.update({'source':source,'requested_month':month,'received_rows':len(rows)})
                    except FetchError as error:
                        finding={'source':source,'requested_month':month,'status':'request_failed','error_code':str(error)}
                        if month:source_ok=False
                        diagnostics.append(finding)
                        if str(error).startswith(('http_401','http_403','http_429','missing_secret','credential_echo','pause_safety')):raise
                        continue
                    diagnostics.append(finding)
                    if month and not finding['matches_requested_month']:source_ok=False
                if source_ok:chosen=source;break
            if chosen is None:raise FetchError('blocked_no_verified_historical_source')
            state=checkpoint(chosen);save(ROOT/'checkpoint.json',state)
        save(OUT/'source-diagnostic.json',{'attempts':diagnostics,'source':state['source'],'dates_are_monitoring_metadata_not_credentials':True})
        phase='full_year_download'
        for month,entry in sorted(state['months'].items()):
            known={p['sha256'] for p in entry['pages']}
            while not entry['complete']:
                if len(entry['pages'])>=250:raise FetchError('pause_month_page_safety_limit')
                rows=client.get(state['source'],month,entry['next_offset'],1000)
                if not rows:
                    if not entry['pages']:raise FetchError('empty_month_not_complete')
                    entry['complete']=True;entry['termination']='observed_empty_page';save(ROOT/'checkpoint.json',state);break
                validation=inspect(rows,month)
                if not validation['matches_requested_month']:
                    diagnostics.append({'source':state['source'],'requested_month':month,'offset':entry['next_offset'],**validation});raise FetchError('blocked_download_date_or_schema_mismatch')
                raw=json.dumps(rows,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode('utf-8');sha=hashlib.sha256(raw).hexdigest()
                if sha in known:raise FetchError('blocked_repeated_page')
                offset=entry['next_offset'];name=month+'/'+str(offset)+'.json.gz';path=ROOT/name;path.parent.mkdir(parents=True,exist_ok=True)
                tmp=path.with_suffix('.tmp');tmp.write_bytes(gzip.compress(raw,mtime=0));tmp.replace(path)
                entry['pages'].append({'offset':offset,'file':name,'rows':len(rows),'sha256':sha});entry['next_offset']+=len(rows);known.add(sha);save(ROOT/'checkpoint.json',state)
        phase='station_day_item_audit';seen={};duplicates=0;items=Counter();stations=set()
        for month,entry in state['months'].items():
            for p in entry['pages']:
                for r in json.loads(gzip.decompress((ROOT/p['file']).read_bytes())):
                    key=(str(r['sitename']),str(r['itemname']),parse_date(r['monitordate']).isoformat());digest=hashlib.sha256(json.dumps(r,sort_keys=True,ensure_ascii=False,allow_nan=False).encode()).hexdigest()
                    if key in seen:
                        if seen[key]!=digest:raise FetchError('conflicting_station_day_item_records')
                        duplicates+=1;continue
                    seen[key]=digest;items[key[1]]+=1;stations.add(key[0])
        report.update({'status':'full_year_downloaded_not_yet_annual_analysis','full_year_downloaded':True,'source':state['source'],'unique_station_day_item_records':len(seen),'identical_duplicate_records':duplicates,'station_names':len(stations),'item_record_counts':dict(items)})
    except FetchError as error:report.update({'status':'paused_with_checkpoint' if str(error).startswith('pause_') else 'blocked','failed_phase':phase,'error_code':str(error)})
    except Exception as error:report.update({'status':'failed','failed_phase':phase,'error_type':type(error).__name__})
    finally:
        report['actual_environmental_api_requests']=client.calls
        if state:report['months']={m:{'saved_records':x['next_offset'],'saved_pages':len(x['pages']),'complete_to_empty_page':x['complete']} for m,x in state['months'].items()}
        save(OUT/'source-diagnostic.json',{'attempts':diagnostics,'source':state.get('source') if state else None,'phase':phase,'actions_run_url':report['actions_run_url']})
        save(OUT/'download-status.json',report);save(ROOT/'download-status.json',report)
    if not report['full_year_downloaded']:raise SystemExit(1)
def self_test():
    assert parse_date('2024-01-02').isoformat()=='2024-01-02'
    assert parse_date('2024/1/2 00:00:00').isoformat()=='2024-01-02'
    assert parse_date('2024年1月2日').isoformat()=='2024-01-02'
    assert parse_date('20240229').isoformat()=='2024-02-29'
    assert parse_date('2024-02-30') is None and parse_date('unknown') is None
    row={'sitename':'test','itemname':'PM2.5','monitordate':'2024-01-01',**{k:'0' for k in HOURS}}
    assert inspect([row],'2024_01')['matches_requested_month']
    row['monitordate']='2026-01-01';assert inspect([row],'2024_01')['counts']['wrong_month']==1
    row['monitordate']='bad';assert inspect([row],'2024_01')['counts']['unrecognized_date_format']==1
    row['monitordate']=None;assert inspect([row],'2024_01')['counts']['missing_date']==1
    return {'synthetic_checks_passed':9,'real_api_requests':0}
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--self-test',action='store_true');args=p.parse_args()
    if args.self_test:print(json.dumps(self_test()))
    else:run()
