import csv,hashlib,json,math,os,re,time,unicodedata
from collections import Counter,defaultdict
from datetime import datetime,timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode,quote,quote_plus
from urllib.request import Request,build_opener
from bs4 import BeautifulSoup
from official_income import COUNTIES,FIELDS,norm
from download_moenv import NoRedirect,records
ROOT=Path('pollution-acquisition');REPORT=Path('reports/pollution-acquisition/status.json')
class Client:
    def __init__(self,key):self.key=key;self.calls=0;self.started=time.monotonic();self.blocked=False
    def get(self,dataset,month=None,offset=0,limit=100):
        if dataset not in ('AQX_P_547','AQX_P_07'):return [],{'status':'unsupported_dataset'}
        if not self.key:return [],{'status':'missing_secret'}
        if self.blocked:return [],{'status':'skipped_auth_failure'}
        if self.calls>=14 or time.monotonic()-self.started>480:return [],{'status':'budget_reached'}
        params={'api_key':self.key,'format':'json','offset':offset,'limit':limit}
        if month:params['year_month']=month
        self.calls+=1
        try:
            url='https://data.moenv.gov.tw/api/v2/'+dataset.lower()+'?'+urlencode(params)
            with build_opener(NoRedirect()).open(Request(url,headers={'Accept':'application/json'}),timeout=35) as response:raw=response.read(5000001)
            if len(raw)>5000000:return [],{'status':'response_too_large'}
            if any(v.encode() in raw for v in (self.key,quote(self.key,safe=''),quote_plus(self.key))):return [],{'status':'credential_echo_rejected'}
            rows=records(json.loads(raw.decode('utf-8-sig')))
            if len(rows)>limit:return [],{'status':'limit_not_honored'}
            cleaned=[]
            for row in rows:
                r={str(k).lower():v for k,v in row.items()}
                if len(r)!=len(row):return [],{'status':'field_collision'}
                cleaned.append(r)
            return cleaned,{'status':'received' if rows else 'empty','rows':len(rows),'response_sha256':hashlib.sha256(raw).hexdigest(),'fields':sorted(set().union(*(r.keys() for r in cleaned))) if cleaned else []}
        except HTTPError as error:
            if error.code in (401,403):self.blocked=True
            return [],{'status':'http_error','http_status':error.code}
        except Exception as error:return [],{'status':'request_or_decode_failed','error_type':type(error).__name__}
def number(value):
    n=float(unicodedata.normalize('NFKC',str(value)).replace(',',''))
    if not math.isfinite(n) or n<0:raise ValueError('Invalid aggregate number')
    return n
def township_rows(raw,county):
    children=defaultdict(list);totals=defaultdict(list);town='';issues=Counter()
    for tr in BeautifulSoup(raw,'html.parser').find_all('tr'):
        cells=tr.find_all('td',recursive=False)
        if len(cells)!=12:continue
        c=[re.sub(r'\s+','',td.get_text(' ',strip=True)) for td in cells]
        if c[2] in ('','村里','村里別'):continue
        if c[1]:town=c[1] if c[1] not in ('鄉鎮市區','合計','小計','總計','其他') and c[1].endswith(('鄉','鎮','市','區')) else ''
        if not town:continue
        try:
            nums=[number(v) for v in c[3:11]]
            if nums[0]!=int(nums[0]) or not nums[4]<=nums[3]<=nums[5]:raise ValueError('Invalid aggregate quantile')
        except (ValueError,TypeError):issues['unparsed_numeric_rows']+=1;continue
        if c[2] in ('合計','小計'):totals[town].append(nums)
        elif c[2]!='總計':children[town].append(nums)
    output=[]
    for name in sorted(set(children)|set(totals)):
        child=children[name];accepted=[]
        for n in totals[name]:
            if child and n[0]==sum(x[0] for x in child) and abs(n[1]-sum(x[1] for x in child))<=max(1,len(child)):accepted.append(n)
            else:issues['aggregate_not_reconciled']+=1
        unique={tuple(x) for x in accepted}
        if len(unique)!=1:issues['township_missing_or_ambiguous_aggregate']+=1;continue
        n=list(unique.pop());row={'county':county,'township':name,'income_year':2024,'unit':'thousand_TWD',**dict(zip(FIELDS,n)),'verification':'official_aggregate_reconciled_with_child_filing_units_and_total'};row['納稅單位']=int(n[0]);output.append(row)
    return output,dict(issues)
def extract_income():
    root=Path('income-source');meta=json.loads((root/'official-source.json').read_text(encoding='utf-8'));iq=json.loads(Path('environment-preview/income-quality.json').read_text(encoding='utf-8'))
    archive=(root/'official-html.zip').read_bytes()
    if hashlib.sha256(archive).hexdigest()!=iq['official_archive_sha256'] or meta.get('income_year')!=2024:raise ValueError('Income archive provenance mismatch')
    stats={x['county']:x for x in meta['county_stats']};rows=[];audit=[]
    for region,county in COUNTIES.items():
        raw=(root/(region+'.html')).read_bytes()
        if hashlib.sha256(raw).hexdigest()!=stats[county]['sha256']:raise ValueError('Income HTML checksum mismatch')
        text=norm(BeautifulSoup(raw,'html.parser').get_text())
        if not all(v in text for v in ('165','113','中位數','千元',norm(county))):raise ValueError('Income HTML identity mismatch')
        found,issues=township_rows(raw,county);rows.extend(found);audit.append({'county':county,'verified_aggregate_rows':len(found),'issues':issues})
    if rows:
        with (ROOT/'township-income-candidates.csv').open('w',encoding='utf-8-sig',newline='') as f:
            writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    return rows,{'status':'reconciled_aggregate_candidates' if rows else 'needs_layout_review','county_files_verified':len(audit),'township_rows':len(rows),'county_audit':audit,'all_administrative_townships_covered_verified':False,'unit':'thousand_TWD','income_definition':'tax_filing_units_comprehensive_income_not_complete_household_disposable_income'}
def requested_month(rows,month):
    if not rows:return None
    expected=month.replace('_','-')
    for row in rows:
        m=re.match(r'^(\d{4})[-/](\d{1,2})',str(row.get('monitordate','')))
        if not m or m[1]+'-'+m[2].zfill(2)!=expected:return False
    return True
def main():
    ROOT.mkdir(exist_ok=True);client=Client(os.environ.get('MOENV_API_KEY','').strip())
    result={'checked_at_utc':datetime.now(timezone.utc).isoformat(),'target_year':2024,'scope':'township_data_acquisition_preflight','full_year_downloaded':False,'annual_concentrations_computed':False,'site_changed':False,'api_request_limit':14,'automatic_retries':False,'monthly_samples':[],'actions_run_url':'https://github.com/'+os.environ.get('GITHUB_REPOSITORY','')+'/actions/runs/'+os.environ.get('GITHUB_RUN_ID','')}
    incomes=[]
    try:incomes,result['income']=extract_income()
    except Exception as error:result['income']={'status':'not_acquired_or_not_reconciled','error_type':type(error).__name__}
    stations,station_meta=client.get('AQX_P_07',limit=1000)
    if stations:
        tail,tail_meta=client.get('AQX_P_07',offset=len(stations),limit=1)
        station_meta['observed_empty_next_page']=tail_meta['status']=='empty';station_meta['next_page_status']=tail_meta['status']
    allowed=('siteid','sitename','county','township','sitetype','twd97lon','twd97lat','longitude','latitude','siteaddress')
    saved=[{k:r.get(k) for k in allowed if k in r} for r in stations]
    (ROOT/'station-metadata.json').write_text(json.dumps(saved,ensure_ascii=False,indent=2),encoding='utf-8')
    keys={(norm(r['county']),norm(r['township'])) for r in incomes}
    station_meta.update({'current_metadata_only':True,'historical_station_status_2024_verified':False,'stations_with_candidate_income_match':sum((norm(r.get('county')),norm(r.get('township'))) in keys for r in saved),'unmatched_station_count':sum((norm(r.get('county')),norm(r.get('township'))) not in keys for r in saved)})
    result['stations']=station_meta;history_supported=True
    for m in range(1,13):
        month='2024_'+str(m).zfill(2)
        if not history_supported:result['monthly_samples'].append({'month':month,'status':'skipped_year_month_not_honored'});continue
        rows,meta=client.get('AQX_P_547',month=month,limit=100);honored=requested_month(rows,month)
        meta.update({'month':month,'requested_month_honored':honored,'full_month_downloaded':False,'quality_rules_verified':False})
        if honored is False:meta['status']='year_month_not_honored';history_supported=False
        pm=[r for r in rows if str(r.get('itemname') or r.get('itemengname') or '').replace(' ','').upper() in ('PM2.5','PM25','細懸浮微粒')] if honored else []
        meta['pm25_rows_seen_in_sample']=len(pm);meta['pm25_unit_labels_seen']=sorted({str(r['itemunit']) for r in pm if r.get('itemunit')});meta['pm25_not_seen_does_not_prove_absence']=True
        if honored:
            fields=('siteid','sitename','monitordate','itemname','itemengname','itemunit')+tuple('monitorvalue'+str(h).zfill(2) for h in range(24))
            projected=[{k:r[k] for k in fields if k in r} for r in rows]
            (ROOT/(month+'-sample.json')).write_text(json.dumps(projected,ensure_ascii=False),encoding='utf-8')
        result['monthly_samples'].append(meta)
    result['actual_environmental_api_requests']=client.calls
    result['status']='preflight_completed_not_full_dataset'
    result['next_required']='Review month/schema/unit results, then approve a bounded resumable full-year download; verify historical station changes before analysis.'
    REPORT.parent.mkdir(parents=True,exist_ok=True);REPORT.write_text(json.dumps(result,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
    (ROOT/'status.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
if __name__=='__main__':main()
