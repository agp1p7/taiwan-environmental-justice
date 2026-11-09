import csv,gzip,hashlib,json,math,os,re,sys,time,unicodedata
from collections import defaultdict
from datetime import date,datetime,timedelta,timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode,quote,quote_plus
from urllib.request import Request,build_opener
sys.path.insert(0,'scripts')
from download_moenv import NoRedirect,records
ROOT=Path('annual-means');OUT=Path('reports/annual-means')
SOURCES=('AQX_P_15','AQX_P_13');ITEMS=('PM2.5','NO2','SO2');START=date(2024,1,1);END=date(2025,1,1)
HOURS=tuple('monitorvalue'+str(h).zfill(2) for h in range(24))
GLOBAL_MISSING={'2024-06-23','2024-08-31','2024-09-01'}
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
    c=defaultdict(int)
    for r in rows:
        d=parsed(r.get('monitordate'))
        if d is None:c['unparseable_date']+=1
        elif not a<=d<b:c['outside_range']+=1
        if item(r) not in ITEMS:c['unexpected_item']+=1
        if not set(HOURS).issubset(r) or not str(r.get('siteid') or '').strip() or not str(r.get('sitename') or '').strip() or not str(r.get('itemunit') or '').strip():c['missing_fields']+=1
    return bool(rows) and not any(c[k] for k in ('unparseable_date','outside_range','unexpected_item','missing_fields')),dict(c)
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
def load_state():
    p=ROOT/'checkpoint.json'
    if not p.exists():return None
    s=json.loads(p.read_text(encoding='utf-8'))
    fp={'version':2,'source':s.get('source'),'filters':filters(START,END),'sort':'monitordate asc','page_size':1000}
    if s.get('query')!=fp or s.get('source') not in SOURCES:raise Stop('checkpoint_query_mismatch')
    offset=0;seen=set()
    for page in s['pages']:
        name='pages/'+str(offset)+'.json.gz'
        if page['file']!=name or page['offset']!=offset:raise Stop('checkpoint_path_mismatch')
        raw=gzip.decompress((ROOT/name).read_bytes());rows=json.loads(raw);sha=hashlib.sha256(raw).hexdigest()
        ok,_=inspect(rows,START,END)
        if sha!=page['sha256'] or sha in seen or len(rows)!=page['rows'] or not ok or not 0<len(rows)<=1000:raise Stop('checkpoint_integrity_mismatch')
        offset+=len(rows);seen.add(sha)
    if offset!=s['next_offset'] or not isinstance(s.get('complete'),bool):raise Stop('checkpoint_offset_mismatch')
    if s['complete'] and (not s['pages'] or s.get('termination')!='observed_empty_page'):raise Stop('checkpoint_termination_mismatch')
    return s
def compute(s):
    groups=defaultdict(lambda:{'hours':[],'names':set(),'units':set(),'days':set()});seen_keys=set();duplicates=0;global_days_missing=defaultdict(set);expected={START+timedelta(days=i) for i in range((END-START).days)}
    for page in s['pages']:
        for r in json.loads(gzip.decompress((ROOT/page['file']).read_bytes())):
            d=parsed(r['monitordate']);i=item(r);sid=str(r['siteid']).strip();u=str(r['itemunit']).strip();key=(sid,i,d)
            values=[]
            for h in HOURS:
                raw=str(r.get(h,'')).strip()
                try:
                    n=float(unicodedata.normalize('NFKC',raw).replace(',',''))
                    if math.isfinite(n) and n>=0:values.append(n);continue
                except (ValueError,TypeError):pass
                values.append(None)
            if key in seen_keys:
                g=groups[key];duplicates+=1
                g['names'].add(str(r['sitename']));g['units'].add(u);g['days'].add(d)
                g['hours'].extend(v for v in values if v is not None)
                continue
            seen_keys.add(key);g=groups[key]
            g['names'].add(str(r['sitename']));g['units'].add(u);g['days'].add(d);g['hours'].extend(v for v in values if v is not None)
            if d.isoformat() in GLOBAL_MISSING:global_days_missing[i].add(d.isoformat())
    out=[]
    for (sid,i),g in sorted(groups.items()):
        n=len(g['hours'])
        out.append({'siteid':sid,'sitename':'|'.join(sorted(g['names'])),'item':i,'units':'|'.join(sorted(g['units'])),'unit_consistent':len(g['units'])==1,'numeric_hours':n,'numeric_hour_fraction':round(n/8784,4),'distinct_days':len(g['days']),'missing_days':len(expected-g['days']),'annual_mean':round(sum(g['hours'])/n,4) if n else None,'global_missing_dates_not_imputed':sorted(GLOBAL_MISSING),'extra_missing_days':len(expected-g['days']-GLOBAL_MISSING)})
    return {'stations':len({k[0] for k in groups}),'rows':len(out),'global_missing_dates_confirmed':{i:sorted(v) for i,v in global_days_missing.items()},'identical_duplicate_records':duplicates,'station_rows':out}
def run():
    ROOT.mkdir(exist_ok=True);OUT.mkdir(parents=True,exist_ok=True);client=Client();s=None;diagnostics=[];phase='restore'
    report={'status':'started','checked_at_utc':datetime.now(timezone.utc).isoformat(),'target_year':2024,'sources':list(SOURCES),'items':list(ITEMS),'global_missing_dates':sorted(GLOBAL_MISSING),'global_missing_dates_imputed':False,'annual_means_computed':False,'numeric_hours_not_certified_valid_hours':True,'automatic_retries':False,'actions_run_url':'https://github.com/'+os.environ.get('GITHUB_REPOSITORY','')+'/actions/runs/'+os.environ.get('GITHUB_RUN_ID','')}
    try:
        s=load_state();phase='verify_date_range_and_download'
        if s is None:
            chosen=None
            for source in SOURCES:
                ok=True
                for a in (date(2024,1,1),date(2024,7,1),date(2024,12,31)):
                    b=a+timedelta(days=1)
                    try:v,_=inspect(client.get(source,a,b,limit=10),a,b)
                    except Stop as e:
                        v=False
                        if str(e).startswith(('http_401','http_403','http_429','missing_secret','credential_echo','pause_')):raise
                    ok=ok and v
                if ok:chosen=source;break
            if chosen is None:raise Stop('no_source_honors_filters')
            s={'source':chosen,'query':{'version':2,'source':chosen,'filters':filters(START,END),'sort':'monitordate asc','page_size':1000},'pages':[],'next_offset':0,'complete':False};save(ROOT/'checkpoint.json',s)
        report.update({'source':s['source'],'resumed_at_offset':s['next_offset'],'reused_pages':len(s['pages'])});phase='download_filtered_2024';known={p['sha256'] for p in s['pages']}
        while not s['complete']:
            offset=s['next_offset'];rows=client.get(s['source'],START,END,offset)
            if not rows:
                if not s['pages']:raise Stop('unexpected_empty_year')
                s['complete']=True;s['termination']='observed_empty_page';save(ROOT/'checkpoint.json',s);break
            ok,_=inspect(rows,START,END)
            if not ok:diagnostics.append({'offset':offset,'counts':_});raise Stop('range_item_or_schema_not_honored')
            raw=json.dumps(rows,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode();sha=hashlib.sha256(raw).hexdigest()
            if sha in known:raise Stop('repeated_page')
            name='pages/'+str(offset)+'.json.gz';p=ROOT/name;p.parent.mkdir(exist_ok=True);tmp=p.with_suffix('.tmp');tmp.write_bytes(gzip.compress(raw,mtime=0));tmp.replace(p)
            s['pages'].append({'offset':offset,'file':name,'rows':len(rows),'sha256':sha});s['next_offset']+=len(rows);known.add(sha);save(ROOT/'checkpoint.json',s)
            if len(s['pages'])==1 or len(s['pages'])%10==0:print(json.dumps({'saved_pages':len(s['pages']),'saved_records':s['next_offset']}),flush=True)
        phase='compute_annual_means';summary=compute(s)
        report.update({k:v for k,v in summary.items() if k!='station_rows'})
        if summary['stations']<2:raise Stop('insufficient_stations')
        report['global_missing_dates_note']='these days carry no concentration and are not imputed; annual mean skips them'
        report.update({'status':'annual_means_computed','annual_means_computed':True})
        save(OUT/'summary.json',report)
        station_rows=summary['station_rows']
        if station_rows:
            with (OUT/'station-annual-means.csv').open('w',encoding='utf-8-sig',newline='') as f:
                w=csv.DictWriter(f,fieldnames=list(station_rows[0]));w.writeheader();w.writerows(station_rows)
            (ROOT/'station-annual-means.csv').write_bytes((OUT/'station-annual-means.csv').read_bytes())
    except Stop as e:report.update({'status':'blocked','failed_phase':phase,'error_code':str(e)})
    except Exception as e:
        import traceback
        tb=traceback.format_exc()
        report.update({'status':'failed','failed_phase':phase,'error_type':type(e).__name__,'error_message':str(e)[:500],'traceback_last_line':tb.strip().splitlines()[-1] if tb.strip() else None,'traceback_tail':tb.strip().splitlines()[-5:]})
    finally:
        report.update({'actual_api_requests':client.calls,'finished_at_utc':datetime.now(timezone.utc).isoformat()})
        if s:report.update({'saved_records':s['next_offset'],'saved_pages':len(s['pages']),'downloaded_to_empty_page':s['complete']})
        save(OUT/'summary.json',report);save(ROOT/'status.json',report)
    if not report['annual_means_computed']:raise SystemExit(1)
if __name__=='__main__':run()
