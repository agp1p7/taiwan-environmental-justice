import csv, gzip, hashlib, io, json, math, os, re, sys, unicodedata, zipfile
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import numpy as np
from scipy.stats import pearsonr, spearmanr
from bs4 import BeautifulSoup
sys.path.insert(0, 'scripts')
from official_income import download, COUNTIES
from compute_annual_means import load_state, parsed, item, HOURS
OUT=Path('reports/integrated-reanalysis-2024'); OUT.mkdir(parents=True,exist_ok=True)
def norm(v): return re.sub(r'\s+','',unicodedata.normalize('NFKC',str('' if v is None else v))).replace('台','臺').replace('※','')
def load(p): return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def save(name,obj): (OUT/name).write_text(json.dumps(obj,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
def readcsv(p):
    with Path(p).open(encoding='utf-8-sig',newline='') as f: return list(csv.DictReader(f))
def csvout(name,rows):
    if not rows: return
    with (OUT/name).open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
def value(v):
    s=norm(v)
    if not s:return None,'missing'
    if re.fullmatch(r'[+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?',s):
        x=float(s)
        if math.isfinite(x):return x,'numeric_unflagged'
    if any(c in s for c in '#*xXAa'):return None,'invalid_flag'
    return None,'rejected_other'
def corr(x,y):
    if len(x)<3 or np.std(x)==0 or np.std(y)==0:return None
    return float(pearsonr(x,y).statistic)
def partial(x,y,z):
    if len(x)<4:return None
    a=np.column_stack([np.ones(len(z)),z])
    if np.linalg.matrix_rank(a)<2:return None
    rx=np.array(x)-a@np.linalg.lstsq(a,x,rcond=None)[0]
    ry=np.array(y)-a@np.linalg.lstsq(a,y,rcond=None)[0]
    if np.std(rx)<1e-10 or np.std(ry)<1e-10:return None
    return corr(rx,ry)
def stats(rows):
    x=[float(r['income_median_thousand']) for r in rows];y=[float(r['annual_mean']) for r in rows];z=[float(r['population_density']) for r in rows]
    return {'n_stations':len(rows),'n_townships':len({(r['county'],r['township']) for r in rows}),'pearson_r':corr(x,y),'spearman_rho':float(spearmanr(x,y).statistic) if len(x)>=3 and np.std(x)>0 and np.std(y)>0 else None,'partial_r_raw_density':partial(x,y,z),'partial_r_log1p_density':partial(x,y,np.log1p(z))}
def historical(old,density):
    pages=load('reports/station-mapping-review-v2/historical-source-pages.json');entries={}
    pattern=r'^\s*(\d{1,2})\s+(一般測站|背景測站|其他測站|背景兼一般|公園兼一般|一般|背景|公園|交通|工業)\s+(\S+)\s+(.*?)(?=^\s*\d{1,2}\s+(?:一般|背景|公園|交通|工業|其他)|\Z)'
    for p in pages:
        if p['pdf_page_1_based'] not in (77,78,79):continue
        for m in re.finditer(pattern,p['text'],re.M|re.S):
            name=norm(m[3]).removesuffix('站'); body=norm(m[4]);loc=re.search(r'\(([^)]*)\)',body)
            if not loc:raise ValueError('report_location_unparsed')
            county=next((c for c in COUNTIES.values() if norm(c) in loc[1]),None)
            address=body[loc.end():].split('ˇ')[0]
            if name in entries:raise ValueError('duplicate_report_name')
            entries[name]={'county':county or '', 'address':address,'page':p['pdf_page_1_based'],'type':m[2],'quote':m[0].strip()}
    if len(entries)!=78:raise ValueError('report_station_parse_count_'+str(len(entries)))
    rows=[]
    for sid,g in sorted(old.items(),key=lambda x:int(x[0])):
        e=entries.get(norm(g['sitename']));county=e['county'] if e else '';town='';note='';status='pending'
        if e:
            tail=e['address'];prefix=county
            if county=='高雄市' and tail.startswith('高雄縣'):prefix='高雄縣';note='legacy_county_label_normalized'
            if tail.startswith(prefix):tail=tail[len(prefix):]
            candidates=[k.split('|')[1] for k in density if k.startswith(county+'|')]
            found=[t for t in candidates if tail.startswith(t)]
            if tail.startswith('三重市') and county=='新北市':found=['三重區'];note='legacy_city_name_normalized_to_2024_district'
            if len(found)==1:town=found[0];status='supported_by_2024_report_address'
            if norm(g['sitename'])=='善化':status='pending_conflicting_report_address';town='';note='Report says 新營區善化鎮; current metadata alone is insufficient historical proof.'
            if not town and not note:note='No unique township prefix; do not infer from station name.'
        rows.append({'siteid':sid,'sitename':g['sitename'],'old_county':g['county'],'old_township':g['township'],'county_2024':county,'township_2024':town,'historical_status':status,'pdf_page_1_based':e['page'] if e else '', 'report_address':e['address'] if e else '', 'report_type':e['type'] if e else '', 'source_quote':e['quote'] if e else '', 'note':note})
    if len(rows)!=78:raise ValueError('project_station_count')
    csvout('station-history-all-78.csv',rows)
    csvout('historical-pending.csv',[r for r in rows if r['historical_status']!='supported_by_2024_report_address'])
    return {r['siteid']:r for r in rows}
def incomes():
    meta=load('reports/income/official-source.json');p=Path('official-income/official-html.zip')
    if p.exists() and sha(p)!=meta['archive_sha256']:raise ValueError('restored_income_hash_mismatch')
    if not p.exists():
        p.parent.mkdir(exist_ok=True);raw=download(meta['archive_url'],250000000)
        if hashlib.sha256(raw).hexdigest()!=meta['archive_sha256']:raise ValueError('official_income_archive_changed')
        p.write_bytes(raw)
    result={};sources={}
    with zipfile.ZipFile(p) as z:
        for c in meta['county_stats']:
            raw=z.read(c['member'])
            if hashlib.sha256(raw).hexdigest()!=c['sha256']:raise ValueError('income_table_hash_mismatch')
            soup=BeautifulSoup(raw,'html.parser');title=norm(soup.get_text())
            if not all(s in title for s in ('113','165','中位數','千元',norm(c['county']))):raise ValueError('income_title_mismatch')
            last=''
            for tr in soup.find_all('tr'):
                cells=tr.find_all('td',recursive=False)
                if len(cells)!=12:continue
                a=[norm(td.get_text()) for td in cells]
                if a[1] and a[1] not in ('鄉鎮市區','鄉鎮市區別'):last=a[1]
                if a[2] not in ('合計','小計') or not last or last in ('合計','總計','其他'):continue
                if last.startswith(norm(c['county'])):last=last[len(norm(c['county'])):]
                key=norm(c['county'])+'|'+last
                try:v={'income_median_thousand':float(a[6].replace(',','')),'income_mean_thousand':float(a[5].replace(',','')),'filing_units':int(a[3].replace(',',''))}
                except ValueError:continue
                if any(not math.isfinite(x) or x<0 for x in v.values()):raise ValueError('invalid_income_total')
                if key in result and result[key]!=v:raise ValueError('conflicting_township_income_totals')
                result[key]=v;sources[key]=c['member']
    if not result:raise ValueError('no_township_income_totals')
    csvout('township-income-source.csv',[{'key':k,**v,'archive_member':sources[k]} for k,v in sorted(result.items())])
    return result
CAL=[date(2024,1,1)+timedelta(days=i) for i in range(366)]
def quarterly(days):return [sum(d in days for d in CAL if (d.month-1)//3==q) for q in range(4)]
def annuals():
    s=load_state()
    if not s or not s['complete']:raise ValueError('complete_raw_artifact_missing')
    pools={};conflicts=set();dup=0;aux=set();fields=set()
    for page in s['pages']:
        for r in json.loads(gzip.decompress((Path('annual-means')/page['file']).read_bytes())):
            fields.update(r);d=parsed(r['monitordate']);key=(str(int(r['siteid'])),item(r),d)
            flagfields=[k for k in r if re.search(r'(flag|quality|valid|status)',k,re.I) and r[k] not in ('',None)]
            if flagfields:aux.add(key[:2])
            signature=tuple(norm(r.get(h)) for h in HOURS)+(norm(r['itemunit']),norm(r['sitename']))
            if key in pools:
                if pools[key]!=signature:conflicts.add(key)
                else:dup+=1
            else:pools[key]=signature
    group=defaultdict(dict);counts=defaultdict(Counter);units=defaultdict(set);other=Counter()
    for (sid,i,d),v in pools.items():
        g=(sid,i);units[g].add(v[24].lower().replace('μ','u').replace('µ','u'))
        vals=[]
        for raw in v[:24]:
            x,kind=value(raw);counts[g][kind]+=1
            if kind=='rejected_other':other[raw]+=1
            if x is not None:vals.append(x)
        group[g][d]=(sum(vals)/len(vals) if len(vals)>=16 and (sid,i,d) not in conflicts else None,len(vals))
    rows=[];daily=[];qsize=quarterly(set(CAL));need=[math.ceil(.75*n) for n in qsize]
    for (sid,i),data in sorted(group.items()):
        valid={d for d,(mean,n) in data.items() if mean is not None};q=quarterly(valid);reasons=[]
        expected='ug/m3' if i=='PM2.5' else 'ppb'
        if units[(sid,i)]!={expected}:reasons.append('unexpected_or_mixed_units')
        if (sid,i) in aux:reasons.append('uninterpreted_auxiliary_quality_fields')
        if any(a<b for a,b in zip(q,need)):reasons.append('quarter_valid_days_below_75pct')
        if any(k[:2]==(sid,i) for k in conflicts):reasons.append('conflicting_duplicate_daily_records')
        mean=float(np.mean([data[d][0] for d in valid])) if valid else None
        rows.append({'siteid':sid,'item':i,'annual_mean_daily_basis':mean,'valid_days':len(valid),'quarter_valid_days':'|'.join(map(str,q)),'quarter_required_days':'|'.join(map(str,need)),'calendar_missing_days':366-len(data),'unflagged_numeric_hours':counts[(sid,i)]['numeric_unflagged'],'flagged_invalid_hours':counts[(sid,i)]['invalid_flag'],'blank_hours_in_present_records':counts[(sid,i)]['missing'],'other_rejected_hours':counts[(sid,i)]['rejected_other'],'units':'|'.join(sorted(units[(sid,i)])),'eligible_under_documented_rules':not reasons,'exclusion_reasons':'|'.join(reasons),'official_validity_certified':False})
        for d in CAL:
            m,n=data.get(d,(None,0));daily.append({'siteid':sid,'item':i,'date':d.isoformat(),'record_present':d in data,'unflagged_hours':n,'daily_mean':m,'valid_day_under_rules':m is not None})
    csvout('annual-quality.csv',rows);csvout('daily-quality.csv',daily)
    save('raw-audit.json',{'checkpoint_sha256':sha('annual-means/checkpoint.json'),'raw_pages':len(s['pages']),'duplicate_identical_records_removed':dup,'conflicting_duplicate_keys':[list(k[:2])+[k[2].isoformat()] for k in sorted(conflicts)],'observed_fields':sorted(fields),'other_rejected_tokens':dict(other),'hourly_sampling_minutes_independently_verified':False,'invalid_flags_policy':'# * x X A a rejected; no flag stripping or zero imputation','quarter_denominators':qsize,'quarter_required_valid_days':need})
    return {(r['siteid'],r['item']):r for r in rows}
def selftest():
    assert value('0')==(0.0,'numeric_unflagged') and value('１２.５')[0]==12.5
    assert all(value(s)[0] is None for s in ('1#','*2','3x','4A','','-1','NaN','inf','ND','<0.1'))
    assert quarterly(set(CAL))==[91,91,92,92]
    assert corr([1,2,3],[2,4,6])>.999
    assert partial([1,2,3,5],[1,3,2,4],[1,2,3,4]) is not None
    return {'status':'passed','checks':'numeric flags zero NFKC leap-year quarters correlations'}
def main():
    report={'status':'started','run_url':'https://github.com/'+os.environ.get('GITHUB_REPOSITORY','')+'/actions/runs/'+os.environ.get('GITHUB_RUN_ID',''),'target_year':2024,'environmental_api_requests':0,'original_analysis_modified':False,'official_certification_claimed':False,'stages':{}}
    oldrows=readcsv('reports/pollution-income-analysis/station-income-density-paired.csv');old={};olditems={}
    for r in oldrows:
        sid=str(int(r['siteid']));key=(sid,r['item'])
        if key in olditems:raise ValueError('duplicate_old_station_item')
        if sid in old and any(norm(old[sid][k])!=norm(r[k]) for k in ('sitename','county','township')):raise ValueError('old_identity_conflict')
        old[sid]=r;olditems[key]=r
    density={norm(k):v for k,v in load('reports/pollution-income-analysis/township-density-2024.json').items()}
    for k,v in density.items():
        if k.split('|')[-1]=='臺灣省':continue
        if v['population']<0 or v['area_km2']<=0 or abs(v['population']/v['area_km2']-v['density'])>.11:raise ValueError('density_arithmetic_mismatch')
    report['selftest']=selftest();hist=inc=means=None
    for name,fn in [('history',lambda:historical(old,density)),('income',incomes),('annual_quality',annuals)]:
        try:
            result=fn();report['stages'][name]={'status':'completed'}
            if name=='history':hist=result
            elif name=='income':inc=result
            else:
                if set(result)!=set(olditems):raise ValueError('raw_station_item_set_differs_from_original')
                means=result
        except Exception as e:report['stages'][name]={'status':'blocked','error_type':type(e).__name__,'error':str(e)[:300]}
    corrected=[];joinissues=[];changes=[]
    if hist and inc:
        for key,r in olditems.items():
            sid,i=key;h=hist[sid];k=h['county_2024']+'|'+h['township_2024'];reasons=[]
            if h['historical_status']!='supported_by_2024_report_address':reasons.append('historical_admin_pending')
            if k not in inc:reasons.append('income_join_missing')
            if k not in density:reasons.append('density_join_missing')
            if reasons:joinissues.append({'siteid':sid,'item':i,'key':k,'reasons':'|'.join(reasons)});continue
            n={**r,'siteid':sid,'county':h['county_2024'],'township':h['township_2024'],**inc[k],'population_density':density[k]['density'],'population':density[k]['population'],'report_pdf_page':h['pdf_page_1_based']}
            corrected.append(n)
            if any(str(n[k])!=str(r[k]) for k in ('county','township','income_median_thousand','population_density')):changes.append({'siteid':sid,'item':i,'old_area':r['county']+'|'+r['township'],'new_area':k,'old_income':r['income_median_thousand'],'new_income':n['income_median_thousand'],'old_density':r['population_density'],'new_density':n['population_density']})
        csvout('mapping-only-repaired-paired.csv',corrected);csvout('join-exclusions.csv',joinissues);csvout('changed-pairings.csv',changes)
    if hist:report['history_counts']=dict(Counter(h['historical_status'] for h in hist.values()))
    if corrected and means:
        final=[];scenarios=defaultdict(list)
        for r in corrected:
            key=(r['siteid'],r['item']);m=means.get(key)
            if not m or not m['eligible_under_documented_rules']:continue
            n={**r,'annual_mean':m['annual_mean_daily_basis'],'valid_days':m['valid_days'],'quarter_valid_days':m['quarter_valid_days'],'official_validity_certified':False};final.append(n)
            oldr=olditems[key]
            for tag,v in [('A_old_same_sample',oldr),('B_mapping_only',r),('C_mean_only',{**oldr,'annual_mean':n['annual_mean']}),('D_mapping_and_mean',n)]:scenarios[(tag,r['item'])].append(v)
        csvout('revised-analysis-paired.csv',final)
        result=[{'scenario':tag,'item':i,**stats(rows)} for (tag,i),rows in sorted(scenarios.items())]
        for i in ('NO2','PM2.5','SO2'):result.append({'scenario':'A_old_all_stations','item':i,**stats([r for r in oldrows if r['item']==i])})
        csvout('old-new-statistics.csv',result)
        within=[]
        for (tag,i),rr in scenarios.items():
            if tag not in ('A_old_same_sample','D_mapping_and_mean'):continue
            for county in sorted({r['county'] for r in rr}):
                v=[r for r in rr if r['county']==county]
                if len(v)>=5:within.append({'scenario':tag,'item':i,'county':county,**stats(v)})
        csvout('within-county.csv',within)
        report.update({'statistics':result,'revised_station_item_rows':len(final),'revised_unique_stations':len({r['siteid'] for r in final}),'status':'completed_with_explicit_exclusions' if joinissues or len(final)!=234 else 'completed'})
    else:report['status']='partial_or_blocked_no_final_statistics'
    report['limitations']=['2024 report supports administrative assignment, not continuous station operation or historical coordinates.','Unresolved historical addresses and unmatched socioeconomic keys excluded explicitly.','Conservative unflagged finite nonnegative values used; unknown tokens rejected, never stripped or imputed.','Official 45-minute hourly sampling validity cannot be certified from these exported values.','Year means are equal-weight means of days with at least 16 accepted hours; each quarter must reach 75% of calendar days.','Correlations use stations, not independent townships or personal exposures; no causal conclusion.','A/B/C/D on the same final sample separates mapping changes, mean changes and joint effects.','Raw density reproduces original control specification; log1p density is a sensitivity model.']
    report['input_sha256']={p:sha(p) for p in ['reports/pollution-income-analysis/station-income-density-paired.csv','reports/pollution-income-analysis/township-density-2024.json','reports/station-mapping-review-v2/historical-source-pages.json','reports/income/official-source.json']}
    report['finished_at_utc']=datetime.now(timezone.utc).isoformat();save('summary.json',report)
    lines=['# Integrated 2024 reanalysis','', 'Status: '+report['status'],'','## Stage status']+[f'- {k}: {v}' for k,v in report['stages'].items()]+['','## Statistics','', '| Scenario | Item | n | Pearson | Spearman | Partial raw density |','|---|---|---:|---:|---:|---:|']
    for r in report.get('statistics',[]):lines.append('| '+' | '.join(str(r[k]) for k in ('scenario','item','n_stations','pearson_r','spearman_rho','partial_r_raw_density'))+' |')
    lines+=['','## Interpretation','Compare A_old_all_stations with A_old_same_sample for sample-selection effects; A vs B for mapping; A vs C for daily-mean/duplicate handling; A vs D for joint changes. These are descriptive changes, not causal effects.','', '## Limitations']+['- '+s for s in report['limitations']]
    (OUT/'REPORT.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    if not corrected or not means or not report.get('revised_station_item_rows'):raise SystemExit(1)
if __name__=='__main__':
    try:main()
    except Exception as e:
        save('fatal.json',{'status':'blocked','error_type':type(e).__name__,'error':str(e)[:300],'original_analysis_modified':False});raise SystemExit(1)
