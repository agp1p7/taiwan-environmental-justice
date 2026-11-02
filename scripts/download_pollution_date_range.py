import argparse,csv,gzip,hashlib,json,math,os,re,time,unicodedata
from collections import Counter,defaultdict
from datetime import date,datetime,timedelta,timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode,quote,quote_plus
from urllib.request import Request,build_opener
from download_moenv import NoRedirect,records
ROOT=Path('pollution-date-range');OUT=Path('reports/pollution-date-range')
SOURCES=('AQX_P_15','AQX_P_13');ITEMS=('PM2.5','NO2','SO2');START=date(2024,1,1);END=date(2025,1,1)
HOURS=tuple('monitorvalue'+str(h).zfill(2) for h in range(24))
class Stop(ValueError):pass
def save(p,obj):
    p.parent.mkdir(parents=True,exist_ok=True);t=p.with_suffix(p.suffix+'.tmp');t.write_text(json.dumps(obj,ensure_ascii=False,separators=(',',':'),allow_nan=False),encoding='utf-8');t.replace(p)
def parsed(v):
    s=unicodedata.normalize('NFKC',str(v or '')).strip().lstrip(chr(65279)).strip();m=re.match(r'^(\d{4})[-/年](\d{1,2})[-/月](\d{1,2})(?:日|T| |$)',s)
    if not m:return None
    try:return date(*map(int,m.groups()))
    except ValueError:return None
def item(r):return unicodedata.normalize('NFKC',str(r.get('itemengname') or '')).strip().upper()
def filters(a,b):return 'monitordate,GR,'+a.isoformat()+'|monitordate,LT,'+b.isoformat()+'|itemengname,EQ,'+','.join(ITEMS)
def inspect(rows,a,b):
    c=Counter();examples=[]
    for r in rows:
        d=parsed(r.get('monitordate'));c['rows']+=1
        if len(examples)<3 and str(r.get('monitordate')) not in examples:examples.append(str(r.get('monitordate'))[:64])
        if d is None:c['unparseable_date']+=1
        elif not a<=d<b:c['outside_requested_range']+=1
        if item(r) not in ITEMS:c['unexpected_item']+=1
        if not set(HOURS).issubset(r) or not all(str(r.get(k) or '').strip() for k in ('siteid','sitename','itemunit')):c['missing_required_fields']+=1
    return {'verified':bool(rows) and not any(c[k] for k in ('unparseable_date','outside_requested_range','unexpected_item','missing_required_fields')),'counts':dict(c),'date_examples':examples,'station_ids_seen':sorted({str(r.get('siteid')) for r in rows})}
class Client:
    def __init__(self):self.key=os.environ.get('MOENV_API_KEY','').strip();self.calls=0;self.start=time.monotonic();self.last=0
    def get(self,source,a,b,offset=0,limit=1000):
        if source not in SOURCES:raise Stop('unapproved_source')
        if not self.key:raise Stop('missing_secret')
        if self.calls>=3000 or time.monotonic()-self.start>6300:raise Stop('pause_safety_limit')
        time.sleep(max(0,1-(time.monotonic()-self.last)));self.calls+=1;self.last=time.monotonic()
        p={'api_key':self.key,'format':'json','limit':limit,'offset':offset,'sort':'monitordate asc','filters':filters(a,b)}
        try:
            url='https://data.moenv.gov.tw/api/v2/'+source.lower()+'?'+urlencode(p)
            with build_opener(NoRedirect()).open(Request(url,headers={'Accept':'application/json'}),timeout=40) as response:raw=response.read(20000001)
        except HTTPError as e:raise Stop('http_'+str(e.code)) from None
        except Exception as e:raise Stop('transport_'+type(e).__name__) from None
        if len(raw)>20000000:raise Stop('response_too_large')
        if any(v.encode() in raw for v in (self.key,quote(self.key,safe=''),quote_plus(self.key))):raise Stop('credential_echo_rejected')
        try:rows=records(json.loads(raw.decode('utf-8-sig')))
        except Exception:raise Stop('invalid_json_or_records') from None
        if len(rows)>limit:raise Stop('limit_not_honored')
        result=[]
        for row in rows:
            r={str(k).lower():v for k,v in row.items()}
            if len(r)!=len(row):raise Stop('field_collision')
            result.append(r)
        if self.key in json.dumps(result,ensure_ascii=False):raise Stop('credential_echo_rejected')
        return result
def fingerprint(source):return {'version':1,'source':source,'filters':filters(START,END),'sort':'monitordate asc','page_size':1000}
def restore():
    p=ROOT/'checkpoint.json'
    if not p.exists():return None
    s=json.loads(p.read_text(encoding='utf-8'))
    if s.get('source') not in SOURCES or s.get('query')!=fingerprint(s['source']):raise Stop('checkpoint_query_mismatch')
    offset=0;seen=set()
    for page in s['pages']:
        name='pages/'+str(offset)+'.json.gz'
        if page['file']!=name or page['offset']!=offset:raise Stop('checkpoint_path_mismatch')
        raw=gzip.decompress((ROOT/name).read_bytes());rows=json.loads(raw);sha=hashlib.sha256(raw).hexdigest()
        if sha!=page['sha256'] or sha in seen or len(rows)!=page['rows'] or not 0<len(rows)<=1000 or not inspect(rows,START,END)['verified']:raise Stop('checkpoint_integrity_mismatch')
        offset+=len(rows);seen.add(sha)
    if offset!=s['next_offset'] or not isinstance(s.get('complete'),bool):raise Stop('checkpoint_offset_mismatch')
    if s['complete'] and (not s['pages'] or s.get('termination')!='observed_empty_page'):raise Stop('checkpoint_termination_mismatch')
    return s
def audit(s):
    seen={};duplicates=0;groups={};global_days={i:set() for i in ITEMS};units={i:set() for i in ITEMS};month_stations=defaultdict(set)
    for page in s['pages']:
        for r in json.loads(gzip.decompress((ROOT/page['file']).read_bytes())):
            d=parsed(r['monitordate']);i=item(r);sid=str(r['siteid']).strip();u=str(r['itemunit']).strip();key=(sid,i,d)
            values=tuple(str(r.get(h,'')).strip() for h in HOURS);digest=hashlib.sha256(json.dumps((u,values),ensure_ascii=False).encode()).hexdigest()
            if key in seen:
                if seen[key]!=digest:raise Stop('conflicting_station_item_day_records')
                duplicates+=1;continue
            seen[key]=digest;g=groups.setdefault((sid,i),{'days':set(),'names':set(),'units':set(),'numeric':0,'non_numeric_or_negative':0})
            g['days'].add(d);g['names'].add(str(r['sitename']));g['units'].add(u);global_days[i].add(d);units[i].add(u);month_stations[d.strftime('%Y-%m')].add(sid)
            for v in values:
                try:n=float(v);good=math.isfinite(n) and n>=0
                except (ValueError,TypeError):good=False
                g['numeric' if good else 'non_numeric_or_negative']+=1
    expected={START+timedelta(days=i) for i in range((END-START).days)};rows=[]
    for (sid,i),g in sorted(groups.items()):
        rows.append({'siteid':sid,'sitenames':'|'.join(sorted(g['names'])),'itemengname':i,'units':'|'.join(sorted(g['units'])),'unit_label_consistent':len(g['units'])==1,'distinct_days':len(g['days']),'missing_days':len(expected-g['days']),'nonnegative_finite_numeric_hours':g['numeric'],'non_numeric_negative_or_nonfinite_hours':g['non_numeric_or_negative'],'calendar_hours':8784,'numeric_hour_fraction_of_calendar_year':g['numeric']/8784,**{f'days_{m:02d}':sum(d.month==m for d in g['days']) for m in range(1,13)}})
    if rows:
        with (ROOT/'station-item-coverage.csv').open('w',encoding='utf-8-sig',newline='') as f:
            w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
        (OUT/'station-item-coverage.csv').write_bytes((ROOT/'station-item-coverage.csv').read_bytes())
    return {'unique_station_item_day_records':len(seen),'identical_duplicate_records':duplicates,'station_count':len({k[0] for k in groups}),'station_ids':sorted({k[0] for k in groups}),'units_by_item':{i:sorted(v) for i,v in units.items()},'missing_global_dates_by_item':{i:[d.isoformat() for d in sorted(expected-v)] for i,v in global_days.items()},'monthly_station_counts':{m:len(v) for m,v in sorted(month_stations.items())},'coverage_rows':len(rows)}
def run():
    ROOT.mkdir(exist_ok=True);OUT.mkdir(parents=True,exist_ok=True);client=Client();s=None;diagnostics=[];phase='restore'
    report={'status':'started','checked_at_utc':datetime.now(timezone.utc).isoformat(),'target_year':2024,'requested_items':list(ITEMS),'filters':filters(START,END),'year_month_parameter_used':False,'full_year_query_completed':False,'annual_concentrations_computed':False,'site_changed':False,'national_station_completeness_verified':False,'historical_station_metadata_verified':False,'annual_qa_status_verified':False,'numeric_hours_are_not_certified_valid_hours':True,'automatic_retries':False,'actions_run_url':'https://github.com/'+os.environ.get('GITHUB_REPOSITORY','')+'/actions/runs/'+os.environ.get('GITHUB_RUN_ID','')}
    try:
        s=restore();phase='verify_disjoint_date_ranges'
        if s is None:
            chosen=None
            for source in SOURCES:
                ok=True
                for a in (date(2024,1,1),date(2024,7,1),date(2024,12,31)):
                    b=a+timedelta(days=1)
                    try:v=inspect(client.get(source,a,b,limit=10),a,b)
                    except Stop as e:
                        v={'verified':False,'error_code':str(e)}
                        if str(e).startswith(('http_401','http_403','http_429','missing_secret','credential_echo','pause_')):raise
                    diagnostics.append({'source':source,'filters':filters(a,b),**v});ok=ok and v['verified']
                if ok:chosen=source;break
            if chosen is None:raise Stop('no_source_honors_date_and_item_filters')
            s={'source':chosen,'query':fingerprint(chosen),'pages':[],'next_offset':0,'complete':False};save(ROOT/'checkpoint.json',s)
        report.update({'source':s['source'],'resumed_at_offset':s['next_offset'],'reused_pages':len(s['pages'])});phase='download_filtered_2024';known={p['sha256'] for p in s['pages']}
        while not s['complete']:
            offset=s['next_offset'];rows=client.get(s['source'],START,END,offset)
            if not rows:
                if not s['pages']:raise Stop('unexpected_empty_year')
                s['complete']=True;s['termination']='observed_empty_page';save(ROOT/'checkpoint.json',s);break
            v=inspect(rows,START,END)
            if not v['verified']:diagnostics.append({'source':s['source'],'offset':offset,**v});raise Stop('range_item_or_schema_not_honored')
            raw=json.dumps(rows,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode();sha=hashlib.sha256(raw).hexdigest()
            if sha in known:raise Stop('repeated_page')
            name='pages/'+str(offset)+'.json.gz';p=ROOT/name;p.parent.mkdir(exist_ok=True);tmp=p.with_suffix('.tmp');tmp.write_bytes(gzip.compress(raw,mtime=0));tmp.replace(p)
            s['pages'].append({'offset':offset,'file':name,'rows':len(rows),'sha256':sha});s['next_offset']+=len(rows);known.add(sha);save(ROOT/'checkpoint.json',s)
            if len(s['pages'])==1 or len(s['pages'])%10==0:print(json.dumps({'source':s['source'],'saved_pages':len(s['pages']),'saved_2024_records':s['next_offset']}),flush=True)
        phase='station_item_coverage_audit';coverage=audit(s);report.update(coverage)
        if coverage['station_count']<2:raise Stop('single_station_not_sufficient')
        if any(coverage['missing_global_dates_by_item'].values()):raise Stop('incomplete_global_item_date_coverage')
        report.update({'status':'multi_station_year_query_completed_not_yet_annual_analysis','full_year_query_completed':True})
    except Stop as e:report.update({'status':'paused_with_checkpoint' if str(e).startswith('pause_') else 'blocked','failed_phase':phase,'error_code':str(e)})
    except Exception as e:report.update({'status':'failed','failed_phase':phase,'error_type':type(e).__name__})
    finally:
        report.update({'actual_api_requests':client.calls,'finished_at_utc':datetime.now(timezone.utc).isoformat()})
        if s:report.update({'saved_records':s['next_offset'],'saved_pages':len(s['pages']),'downloaded_to_empty_page':s['complete']})
        save(OUT/'query-diagnostic.json',{'attempts':diagnostics,'actions_run_url':report['actions_run_url']});save(OUT/'status.json',report);save(ROOT/'status.json',report)
    if not report['full_year_query_completed']:raise SystemExit(1)
def self_test():
    assert filters(START,END)=='monitordate,GR,2024-01-01|monitordate,LT,2025-01-01|itemengname,EQ,PM2.5,NO2,SO2'
    r={'siteid':'1','sitename':'test','itemengname':'PM2.5','itemunit':'ug/m3',**{h:'0' for h in HOURS}}
    for raw in ('2024-01-01 ','2024-12-31 00:00:00','2024/2/29'):
        assert inspect([{**r,'monitordate':raw}],START,END)['verified']
    for raw in ('2023-12-31','2025-01-01','2024-02-30'):
        assert not inspect([{**r,'monitordate':raw}],START,END)['verified']
    r['monitordate']='2024-01-01';assert not inspect([r],date(2024,7,1),date(2024,7,2))['verified']
    assert not inspect([{**r,'itemengname':'CO'}],START,END)['verified']
    broken=dict(r);del broken['itemunit'];assert not inspect([broken],START,END)['verified']
    return {'synthetic_assertions_passed':10,'real_api_requests':0}
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--self-test',action='store_true');args=p.parse_args()
    if args.self_test:print(json.dumps(self_test()))
    else:run()
