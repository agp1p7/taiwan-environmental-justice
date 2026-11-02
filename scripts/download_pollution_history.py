import argparse,calendar,gzip,hashlib,json,os,re,time,unicodedata
from collections import Counter
from datetime import date,datetime,timedelta,timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode,quote,quote_plus
from urllib.request import Request,build_opener
from download_moenv import NoRedirect,records
ROOT=Path('pollution-history');OUT=Path('reports/pollution-history');SOURCE='AQX_P_547'
HOURS=tuple('monitorvalue'+str(h).zfill(2) for h in range(24))
def save(path,obj):
    path.parent.mkdir(parents=True,exist_ok=True);tmp=path.with_suffix(path.suffix+'.tmp')
    tmp.write_text(json.dumps(obj,ensure_ascii=False,separators=(',',':'),allow_nan=False),encoding='utf-8');tmp.replace(path)
def parse_date(value):
    s=unicodedata.normalize('NFKC',str(value or '')).strip().lstrip(chr(65279)).strip()
    m=re.match(r'^(\d{4})[-/年](\d{1,2})[-/月](\d{1,2})(?:日|T| |$)',s)
    if not m:m=re.fullmatch(r'(\d{4})(\d{2})(\d{2})',s)
    if not m:return None
    try:return date(*map(int,m.groups()))
    except ValueError:return None
def inspect(rows):
    counts=Counter();examples=[];schema=True
    for r in rows:
        raw=str(r.get('monitordate') or '');d=parse_date(raw);counts['rows']+=1
        if len(examples)<5 and raw not in [x['raw_date'] for x in examples]:examples.append({'raw_date':raw[:64],'parsed_date':d.isoformat() if d else None})
        if not raw:counts['missing_date']+=1
        elif d is None:counts['unrecognized_date_format']+=1
        elif d.year!=2024:counts['wrong_year']+=1
        else:counts['year_matches']+=1
        if not set(HOURS).issubset(r) or not r.get('sitename') or not r.get('itemname'):schema=False
    return {'year_verified':bool(rows) and schema and not any(counts[k] for k in ('missing_date','unrecognized_date_format','wrong_year')),'hourly_schema_verified':schema,'counts':dict(counts),'date_examples':examples}
class FetchError(ValueError):pass
class Client:
    def __init__(self,key):self.key=key;self.calls=0;self.start=time.monotonic();self.last=0
    def get(self,offset,limit=1000):
        if not self.key:raise FetchError('missing_secret')
        if self.calls>=3000 or time.monotonic()-self.start>6300:raise FetchError('pause_safety_limit')
        time.sleep(max(0,1-(time.monotonic()-self.last)));self.calls+=1;self.last=time.monotonic()
        params={'api_key':self.key,'format':'json','offset':offset,'limit':limit}
        try:
            url='https://data.moenv.gov.tw/api/v2/aqx_p_547?'+urlencode(params)
            with build_opener(NoRedirect()).open(Request(url,headers={'Accept':'application/json'}),timeout=40) as response:body=response.read(20000001)
        except HTTPError as error:raise FetchError('http_'+str(error.code)) from None
        except Exception as error:raise FetchError('transport_'+type(error).__name__) from None
        if len(body)>20000000:raise FetchError('response_too_large')
        if any(v.encode() in body for v in (self.key,quote(self.key,safe=''),quote_plus(self.key))):raise FetchError('credential_echo_rejected')
        try:rows=records(json.loads(body.decode('utf-8-sig')))
        except Exception:raise FetchError('invalid_json_or_records') from None
        if len(rows)>limit:raise FetchError('limit_not_honored')
        normalized=[]
        for row in rows:
            r={str(k).lower():v for k,v in row.items()}
            if len(r)!=len(row):raise FetchError('field_collision')
            normalized.append(r)
        if self.key in json.dumps(normalized,ensure_ascii=False):raise FetchError('credential_echo_rejected')
        return normalized
def load_state():
    path=ROOT/'checkpoint.json'
    if not path.exists():return {'version':2,'source':SOURCE,'target_year':2024,'mode':'unfiltered_annual_snapshot','pages':[],'next_offset':0,'complete':False}
    state=json.loads(path.read_text(encoding='utf-8'))
    if state.get('version')!=2 or state.get('source')!=SOURCE or state.get('target_year')!=2024 or state.get('mode')!='unfiltered_annual_snapshot':raise FetchError('legacy_or_incompatible_checkpoint_requires_review')
    offset=0;seen=set()
    for p in state['pages']:
        name='annual/'+str(offset)+'.json.gz'
        if p['file']!=name or p['offset']!=offset:raise FetchError('checkpoint_path_mismatch')
        raw=gzip.decompress((ROOT/name).read_bytes());sha=hashlib.sha256(raw).hexdigest();rows=json.loads(raw)
        if sha!=p['sha256'] or sha in seen or len(rows)!=p['rows'] or not 0<len(rows)<=1000 or not inspect(rows)['year_verified']:raise FetchError('checkpoint_integrity_mismatch')
        seen.add(sha);offset+=len(rows)
    if offset!=state['next_offset'] or not isinstance(state.get('complete'),bool):raise FetchError('checkpoint_offset_or_completion_mismatch')
    if state['complete'] and (not state['pages'] or state.get('termination')!='observed_empty_page'):raise FetchError('checkpoint_termination_mismatch')
    return state
def audit(state):
    seen={};duplicates=0;items=Counter();months=Counter();days=set();pm_days=set();stations=set()
    for p in state['pages']:
        for r in json.loads(gzip.decompress((ROOT/p['file']).read_bytes())):
            d=parse_date(r['monitordate']);key=(str(r['sitename']),str(r['itemname']),d.isoformat())
            sha=hashlib.sha256(json.dumps(r,sort_keys=True,ensure_ascii=False,allow_nan=False).encode()).hexdigest()
            if key in seen:
                if seen[key]!=sha:raise FetchError('conflicting_station_day_item_records')
                duplicates+=1;continue
            seen[key]=sha;items[key[1]]+=1;months[d.strftime('%Y-%m')]+=1;days.add(d);stations.add(key[0])
            if unicodedata.normalize('NFKC',key[1]).replace(' ','').upper() in ('PM2.5','PM25','細懸浮微粒'):pm_days.add(d)
    expected={date(2024,1,1)+timedelta(days=i) for i in range(366)}
    return {'unique_station_day_item_records':len(seen),'identical_duplicate_records':duplicates,'station_names':len(stations),'item_record_counts':dict(items),'monthly_record_counts':dict(sorted(months.items())),'calendar_dates_present':len(days),'missing_calendar_dates':[d.isoformat() for d in sorted(expected-days)],'pm25_calendar_dates_present':len(pm_days),'pm25_missing_calendar_dates':[d.isoformat() for d in sorted(expected-pm_days)],'station_specific_completeness_verified':False}
def run():
    ROOT.mkdir(exist_ok=True);OUT.mkdir(parents=True,exist_ok=True);client=Client(os.environ.get('MOENV_API_KEY','').strip())
    report={'status':'started','checked_at_utc':datetime.now(timezone.utc).isoformat(),'target_year':2024,'source':SOURCE,'request_mode':'unfiltered_pagination_no_year_month_parameter','full_year_downloaded':False,'annual_concentrations_computed':False,'site_changed':False,'automatic_retries':False,'request_safety_limit':3000,'wall_time_safety_seconds':6300,'minimum_request_interval_seconds':1,'snapshot_consistency_verified':False,'quality_flags_interpreted':False,'actions_run_url':'https://github.com/'+os.environ.get('GITHUB_REPOSITORY','')+'/actions/runs/'+os.environ.get('GITHUB_RUN_ID','')}
    state=None;diagnostics=[];phase='checkpoint_validation'
    try:
        state=load_state();phase='annual_snapshot_download';known={p['sha256'] for p in state['pages']}
        while not state['complete']:
            offset=state['next_offset'];rows=client.get(offset)
            if not rows:
                if not state['pages']:raise FetchError('empty_annual_dataset')
                state['complete']=True;state['termination']='observed_empty_page';save(ROOT/'checkpoint.json',state);break
            validation=inspect(rows)
            if not diagnostics or not validation['year_verified']:diagnostics.append({'offset':offset,**validation})
            if not validation['year_verified']:raise FetchError('blocked_non_2024_date_or_schema')
            raw=json.dumps(rows,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode('utf-8');sha=hashlib.sha256(raw).hexdigest()
            if sha in known:raise FetchError('blocked_repeated_page')
            name='annual/'+str(offset)+'.json.gz';path=ROOT/name;path.parent.mkdir(parents=True,exist_ok=True)
            tmp=path.with_suffix('.tmp');tmp.write_bytes(gzip.compress(raw,mtime=0));tmp.replace(path)
            state['pages'].append({'offset':offset,'file':name,'rows':len(rows),'sha256':sha});state['next_offset']+=len(rows);known.add(sha);save(ROOT/'checkpoint.json',state)
            if len(state['pages'])==1 or len(state['pages'])%10==0:print(json.dumps({'saved_pages':len(state['pages']),'saved_daily_item_records':state['next_offset'],'target_year':2024}),flush=True)
        report['downloaded_to_empty_page']=True;phase='annual_coverage_and_duplicate_audit';coverage=audit(state);report.update(coverage)
        if coverage['missing_calendar_dates']:raise FetchError('blocked_global_calendar_dates_missing')
        if coverage['pm25_missing_calendar_dates']:raise FetchError('blocked_pm25_calendar_dates_missing')
        report.update({'status':'full_year_downloaded_not_yet_annual_analysis','full_year_downloaded':True})
    except FetchError as error:report.update({'status':'paused_with_checkpoint' if str(error).startswith('pause_') else 'blocked','failed_phase':phase,'error_code':str(error)})
    except Exception as error:report.update({'status':'failed','failed_phase':phase,'error_type':type(error).__name__})
    finally:
        report['actual_environmental_api_requests']=client.calls
        if state:report.update({'saved_records':state['next_offset'],'saved_pages':len(state['pages']),'downloaded_to_empty_page':state['complete']})
        save(OUT/'source-diagnostic.json',{'source':SOURCE,'request_mode':report['request_mode'],'page_checks':diagnostics,'phase':phase,'actions_run_url':report['actions_run_url']})
        save(OUT/'download-status.json',report);save(ROOT/'download-status.json',report)
    if not report['full_year_downloaded']:raise SystemExit(1)
def self_test():
    assert parse_date('2024/12/31 00:00').isoformat()=='2024-12-31'
    assert parse_date('2024-01-02').isoformat()=='2024-01-02'
    assert parse_date('2024年1月2日').isoformat()=='2024-01-02'
    assert parse_date('20240229').isoformat()=='2024-02-29'
    assert parse_date(chr(65279)+'2024/1/2').isoformat()=='2024-01-02'
    assert parse_date('2024-02-30') is None
    r={'sitename':'test','itemname':'PM2.5','monitordate':'2024/12/31 00:00',**{h:'0' for h in HOURS}}
    assert inspect([r])['year_verified']
    r['monitordate']='2026-11-01';assert inspect([r])['counts']['wrong_year']==1
    r['monitordate']='bad';assert inspect([r])['counts']['unrecognized_date_format']==1
    r['monitordate']=None;assert inspect([r])['counts']['missing_date']==1
    return {'synthetic_checks_passed':10,'real_api_requests':0}
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--self-test',action='store_true');args=p.parse_args()
    if args.self_test:print(json.dumps(self_test()))
    else:run()
