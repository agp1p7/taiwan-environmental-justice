import argparse,gzip,hashlib,json,os,re,time,unicodedata
from collections import Counter
from datetime import date,datetime,timedelta,timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode,quote,quote_plus
from urllib.request import Request,build_opener
from download_moenv import NoRedirect,records
ROOT=Path('pollution-history');OUT=Path('reports/pollution-history');SOURCE='AQX_P_547'
MODE='scan_source_keep_target_year';HOURS=tuple('monitorvalue'+str(h).zfill(2) for h in range(24))
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
    counts=Counter();years=Counter();examples={};target_schema=True
    for r in rows:
        raw=str(r.get('monitordate') or '');d=parse_date(raw);counts['rows']+=1
        if not raw:counts['missing_date']+=1
        elif d is None:counts['unrecognized_date_format']+=1
        else:
            y=str(d.year);years[y]+=1
            if y not in examples:examples[y]={'raw_date':raw[:64],'parsed_date':d.isoformat()}
            if d.year==2024:
                counts['target_year_rows']+=1
                if not set(HOURS).issubset(r) or not r.get('sitename') or not r.get('itemname'):target_schema=False
            else:counts['non_target_year_rows']+=1
    return {'source_page_usable':bool(rows) and target_schema and not counts['missing_date'] and not counts['unrecognized_date_format'],'target_hourly_schema_verified':target_schema,'counts':dict(counts),'year_counts':dict(years),'date_examples_by_year':examples}
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
    if not path.exists():return {'version':3,'source':SOURCE,'target_year':2024,'mode':MODE,'pages':[],'next_offset':0,'complete':False}
    state=json.loads(path.read_text(encoding='utf-8'));old_version=state.get('version')
    compatible=(old_version==2 and state.get('mode')=='unfiltered_annual_snapshot') or (old_version==3 and state.get('mode')==MODE)
    if not compatible or state.get('source')!=SOURCE or state.get('target_year')!=2024:raise FetchError('incompatible_checkpoint_requires_review')
    offset=0;seen=set()
    for p in state['pages']:
        name='annual/'+str(offset)+'.json.gz'
        if p['file']!=name or p['offset']!=offset:raise FetchError('checkpoint_path_mismatch')
        raw=gzip.decompress((ROOT/name).read_bytes());sha=hashlib.sha256(raw).hexdigest();rows=json.loads(raw);v=inspect(rows)
        if sha!=p['sha256'] or sha in seen or len(rows)!=p['rows'] or not 0<len(rows)<=1000 or not v['source_page_usable']:raise FetchError('checkpoint_integrity_mismatch')
        if old_version==2 and v['year_counts'].get('2024',0)!=len(rows):raise FetchError('legacy_checkpoint_contains_unapproved_years')
        p.update({'year_counts':v['year_counts'],'target_rows':v['year_counts'].get('2024',0)})
        seen.add(sha);offset+=len(rows)
    if offset!=state['next_offset'] or not isinstance(state.get('complete'),bool):raise FetchError('checkpoint_offset_or_completion_mismatch')
    if state['complete'] and (not state['pages'] or state.get('termination')!='observed_empty_page'):raise FetchError('checkpoint_termination_mismatch')
    if old_version==2:state['migrated_from_version']=2
    state.update({'version':3,'mode':MODE});save(path,state)
    return state
def audit(state):
    seen={};duplicates=0;items=Counter();months=Counter();days=set();pm_days=set();stations=set();excluded=Counter()
    for p in state['pages']:
        for r in json.loads(gzip.decompress((ROOT/p['file']).read_bytes())):
            d=parse_date(r['monitordate'])
            if d.year!=2024:excluded[str(d.year)]+=1;continue
            key=(str(r['sitename']),str(r['itemname']),d.isoformat());sha=hashlib.sha256(json.dumps(r,sort_keys=True,ensure_ascii=False,allow_nan=False).encode()).hexdigest()
            if key in seen:
                if seen[key]!=sha:raise FetchError('conflicting_station_day_item_records')
                duplicates+=1;continue
            seen[key]=sha;items[key[1]]+=1;months[d.strftime('%Y-%m')]+=1;days.add(d);stations.add(key[0])
            if unicodedata.normalize('NFKC',key[1]).replace(' ','').upper() in ('PM2.5','PM25','細懸浮微粒'):pm_days.add(d)
    expected={date(2024,1,1)+timedelta(days=i) for i in range(366)}
    return {'unique_station_day_item_records':len(seen),'identical_duplicate_records':duplicates,'station_names':len(stations),'item_record_counts':dict(items),'monthly_record_counts':dict(sorted(months.items())),'calendar_dates_present':len(days),'missing_calendar_dates':[d.isoformat() for d in sorted(expected-days)],'pm25_calendar_dates_present':len(pm_days),'pm25_missing_calendar_dates':[d.isoformat() for d in sorted(expected-pm_days)],'excluded_non_target_year_rows':dict(excluded),'station_specific_completeness_verified':False,'national_station_completeness_verified':False}
def run():
    ROOT.mkdir(exist_ok=True);OUT.mkdir(parents=True,exist_ok=True);client=Client(os.environ.get('MOENV_API_KEY','').strip())
    report={'status':'started','checked_at_utc':datetime.now(timezone.utc).isoformat(),'target_year':2024,'source':SOURCE,'request_mode':'scan_all_source_pages_filter_2024_locally','raw_pages_may_include_other_years':True,'full_year_downloaded':False,'annual_concentrations_computed':False,'site_changed':False,'automatic_retries':False,'request_safety_limit':3000,'wall_time_safety_seconds':6300,'minimum_request_interval_seconds':1,'snapshot_consistency_verified':False,'quality_flags_interpreted':False,'actions_run_url':'https://github.com/'+os.environ.get('GITHUB_REPOSITORY','')+'/actions/runs/'+os.environ.get('GITHUB_RUN_ID','')}
    state=None;diagnostics=[];phase='checkpoint_validation'
    try:
        state=load_state();report['resumed_at_source_offset']=state['next_offset'];report['reused_verified_pages']=len(state['pages']);phase='source_scan_and_2024_selection'
        known={p['sha256'] for p in state['pages']};known_years={y for p in state['pages'] for y in p['year_counts']}
        while not state['complete']:
            offset=state['next_offset'];rows=client.get(offset)
            if not rows:
                if not state['pages']:raise FetchError('empty_source_dataset')
                state['complete']=True;state['termination']='observed_empty_page';save(ROOT/'checkpoint.json',state);break
            v=inspect(rows)
            if not diagnostics or not v['source_page_usable'] or set(v['year_counts'])-known_years:diagnostics.append({'offset':offset,**v})
            if not v['source_page_usable']:raise FetchError('blocked_unparseable_date_or_target_year_schema')
            raw=json.dumps(rows,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode('utf-8');sha=hashlib.sha256(raw).hexdigest()
            if sha in known:raise FetchError('blocked_repeated_page')
            name='annual/'+str(offset)+'.json.gz';path=ROOT/name;path.parent.mkdir(parents=True,exist_ok=True)
            tmp=path.with_suffix('.tmp');tmp.write_bytes(gzip.compress(raw,mtime=0));tmp.replace(path)
            state['pages'].append({'offset':offset,'file':name,'rows':len(rows),'sha256':sha,'year_counts':v['year_counts'],'target_rows':v['year_counts'].get('2024',0)})
            state['next_offset']+=len(rows);known.add(sha);known_years.update(v['year_counts']);save(ROOT/'checkpoint.json',state)
            if len(state['pages'])==report['reused_verified_pages']+1 or len(state['pages'])%10==0:print(json.dumps({'saved_pages':len(state['pages']),'source_records_scanned':state['next_offset'],'saved_2024_daily_item_records':sum(p['target_rows'] for p in state['pages'])}),flush=True)
        report['downloaded_to_empty_page']=True;phase='target_year_coverage_and_duplicate_audit';coverage=audit(state);report.update(coverage)
        if coverage['missing_calendar_dates']:raise FetchError('blocked_global_calendar_dates_missing')
        if coverage['pm25_missing_calendar_dates']:raise FetchError('blocked_pm25_calendar_dates_missing')
        report.update({'status':'full_year_downloaded_not_yet_annual_analysis','full_year_downloaded':True})
    except FetchError as error:report.update({'status':'paused_with_checkpoint' if str(error).startswith('pause_') else 'blocked','failed_phase':phase,'error_code':str(error)})
    except Exception as error:report.update({'status':'failed','failed_phase':phase,'error_type':type(error).__name__})
    finally:
        report['actual_environmental_api_requests']=client.calls;report['finished_at_utc']=datetime.now(timezone.utc).isoformat()
        if state:
            years=Counter()
            for p in state['pages']:years.update(p['year_counts'])
            report.update({'source_records_scanned':state['next_offset'],'saved_pages':len(state['pages']),'saved_target_year_records':years.get('2024',0),'source_row_year_counts':dict(years),'downloaded_to_empty_page':state['complete']})
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
    assert inspect([r])['source_page_usable']
    foreign={**r,'monitordate':'2023/12/31'};mixed=inspect([r,foreign])
    assert mixed['source_page_usable'] and mixed['year_counts']=={'2024':1,'2023':1}
    assert inspect([foreign])['source_page_usable'] and inspect([foreign])['counts'].get('target_year_rows',0)==0
    broken=dict(r);del broken[HOURS[0]];assert not inspect([broken])['source_page_usable']
    r['monitordate']='bad';assert inspect([r])['counts']['unrecognized_date_format']==1 and not inspect([r])['source_page_usable']
    r['monitordate']=None;assert inspect([r])['counts']['missing_date']==1
    return {'synthetic_checks_passed':12,'real_api_requests':0}
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--self-test',action='store_true');args=p.parse_args()
    if args.self_test:print(json.dumps(self_test()))
    else:run()
