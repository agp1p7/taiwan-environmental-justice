import argparse,bisect,csv,hashlib,json,math,os,statistics
from collections import Counter,defaultdict
from pathlib import Path
from datetime import datetime,timezone
METRICS=('air_records','water_records','waste_records','soil_records','ems01_records')
EXPECTED_SHA='dfd7cc65afcc3d8e8c509c2be32c77ef51cc98fb53f3d291f81cf4f7bb5c4afd'
def quantile(values,p):
    a=sorted(values)
    if not a:raise ValueError('Empty quantile input')
    x=(len(a)-1)*p;i=int(x);j=min(i+1,len(a)-1)
    return a[i]+(a[j]-a[i])*(x-i)
def income(value):
    if value is None or isinstance(value,bool) or str(value).strip()=='':return None
    try:
        n=float(value)
        return n if math.isfinite(n) and n>=0 else None
    except (ValueError,TypeError):return None
def collect(geo):
    valid={};excluded=Counter();duplicates=0
    for feature in geo['features']:
        p=feature['properties']
        if not p.get('VILLNAME') or p.get('ems01_records') is None:
            excluded['not_valid_named_boundary_features']+=1;continue
        code=str(p.get('VILLCODE') or '')
        if not code or not p.get('COUNTYNAME'):raise ValueError('Village identity missing')
        row={'code':code,'county':p['COUNTYNAME'],'income':income(p.get('income_median'))}
        for metric in METRICS:
            v=p.get(metric)
            if isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or v<0 or int(v)!=v:raise ValueError('Invalid record count')
            row[metric]=int(v)
        if code in valid:
            if valid[code]!=row:raise ValueError('Conflicting duplicate village')
            duplicates+=1
        else:valid[code]=row
    eligible=[r for r in valid.values() if r['income'] is not None]
    excluded['missing_or_invalid_income_villages']=sum(r['income'] is None for r in valid.values())
    if not eligible:raise ValueError('No eligible villages')
    return list(valid.values()),eligible,dict(excluded),duplicates
def stats(rows,metric):
    a=[r[metric] for r in rows];n=len(a)
    return {'total_records':sum(a),'mean_per_village':statistics.mean(a),'median_per_village':statistics.median(a),'p90_per_village':quantile(a,.9),'zero_villages':sum(x==0 for x in a),'zero_pct':100*sum(x==0 for x in a)/n,'nonzero_villages':sum(x>0 for x in a)}
def compare(geo):
    valid,eligible,excluded,duplicates=collect(geo)
    cuts=sorted(set(quantile([r['income'] for r in eligible],p) for p in (.2,.4,.6,.8)))
    if len(set(r['income'] for r in eligible))==1:cuts=[]
    groups=defaultdict(list)
    for r in eligible:groups[bisect.bisect_left(cuts,r['income'])].append(r)
    totals={m:sum(r[m] for r in eligible) for m in METRICS}
    summaries=[];flat=[];county_rows=[]
    for number,key in enumerate(sorted(groups),1):
        rows=groups[key];label='Q'+str(number)
        entry={'group':label,'villages':len(rows),'income_min':min(r['income'] for r in rows),'income_max':max(r['income'] for r in rows),'income_median':statistics.median(r['income'] for r in rows),'metrics':{}}
        for metric in METRICS:
            s=stats(rows,metric);s['share_of_eligible_records_pct']=100*s['total_records']/totals[metric] if totals[metric] else None
            entry['metrics'][metric]=s
            flat.append({'group':label,'villages':len(rows),'income_min_thousand_TWD':entry['income_min'],'income_max_thousand_TWD':entry['income_max'],'metric':metric,**s})
        summaries.append(entry)
        for county in sorted(set(r['county'] for r in rows)):
            subset=[r for r in rows if r['county']==county]
            for metric in METRICS:county_rows.append({'county':county,'national_income_group':label,'villages':len(subset),'metric':metric,**stats(subset,metric)})
    contrasts={}
    if len(summaries)>1:
        for metric in METRICS:
            lo=summaries[0]['metrics'][metric];hi=summaries[-1]['metrics'][metric]
            contrasts[metric]={'lowest_to_highest_mean_ratio':lo['mean_per_village']/hi['mean_per_village'] if hi['mean_per_village'] else None,'lowest_minus_highest_median':lo['median_per_village']-hi['median_per_village'],'lowest_minus_highest_zero_percentage_points':lo['zero_pct']-hi['zero_pct']}
    report={'status':'computed','income_year':2024,'income_unit':'thousand_TWD','unit_of_analysis':'village_unweighted_not_people','grouping':'up_to_five_groups_by_linear_income_quantiles_right_closed_ties_not_split','cutpoints':cuts,'actual_nonempty_groups':len(summaries),'valid_unique_villages':len(valid),'eligible_villages':len(eligible),'excluded':excluded,'identical_duplicate_features_collapsed':duplicates,'groups':summaries,'lowest_vs_highest':contrasts,'metric_coverage':{m:{'all_valid_village_records':sum(r[m] for r in valid),'included_records':totals[m],'excluded_missing_income_records':sum(r[m] for r in valid if r['income'] is None)} for m in METRICS},'limitations':['Historical management records, not unique current businesses, pollution intensity or exposure.','Only records matched to valid named villages are represented; unmatched source records cannot be allocated to income groups.','No population or area standardization; no causal inference or significance testing.','National comparisons may reflect county, urbanization, industry, village size and source missingness differences.','County tables use national income group cutpoints, not within-county quintiles.','Boundary vintage and snapshot consistency remain unverified.']}
    for metric in METRICS:
        if sum(g['metrics'][metric]['total_records'] for g in summaries)!=totals[metric]:raise ValueError('Group total mismatch')
    return report,flat,county_rows

def self_test():
    def feature(code,value,count):return {'properties':{'VILLCODE':code,'COUNTYNAME':'test_county','VILLNAME':'test_village','income_median':value,**{m:count for m in METRICS}}}
    features=[feature(str(i),100*i,i-1) for i in range(1,6)]
    features+=[feature('missing',None,7),feature('invalid',500,1)]
    features[-1]['properties']['ems01_records']=None
    report,rows,counties=compare({'features':features})
    assert report['eligible_villages']==5 and report['actual_nonempty_groups']==5
    assert report['excluded']['missing_or_invalid_income_villages']==1
    assert report['metric_coverage']['air_records']['included_records']==10
    assert report['metric_coverage']['air_records']['excluded_missing_income_records']==7
    assert report['groups'][0]['metrics']['air_records']['zero_pct']==100
    tied,_,_=compare({'features':[feature(str(i),800,i) for i in range(4)]})
    assert tied['actual_nonempty_groups']==1
    duplicated,_,_=compare({'features':[features[0],features[0]]})
    assert duplicated['eligible_villages']==1 and duplicated['identical_duplicate_features_collapsed']==1
    assert income('') is None and income(False) is None and income(float('nan')) is None
    return {'synthetic_checks_passed':8}
def write_csv(path,rows):
    with path.open('w',encoding='utf-8-sig',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
def main():
    parser=argparse.ArgumentParser();parser.add_argument('--self-test',action='store_true');args=parser.parse_args()
    if args.self_test:print(json.dumps(self_test()));return
    source=Path('environment-preview');raw=(source/'income.geojson').read_bytes();digest=hashlib.sha256(raw).hexdigest()
    if digest!=EXPECTED_SHA:raise ValueError('Published snapshot changed; analysis requires fresh approval')
    iq=json.loads((source/'income-quality.json').read_text(encoding='utf-8'))
    if iq.get('income_year')!=2024 or iq.get('income_unit')!='thousand_TWD':raise ValueError('Income definition mismatch')
    q=json.loads((source/'quality.json').read_text(encoding='utf-8'));c=json.loads((source/'classification-quality.json').read_text(encoding='utf-8'))
    report,rows,counties=compare(json.loads(raw))
    expected={'ems01_records':q['datasets']['EMS_S_01']['counts']['spatial_matched'],'soil_records':q['datasets']['EMS_S_07']['counts']['spatial_matched'],**{k+'_records':c['categories'][k]['counts']['matched_yes'] for k in ('air','water','waste')}}
    if report['valid_unique_villages']!=q['valid_named_boundary_features'] or any(report['metric_coverage'][m]['all_valid_village_records']!=expected[m] for m in METRICS):raise ValueError('Published totals reconciliation failed')
    report.update({'computed_at_utc':datetime.now(timezone.utc).isoformat(),'input_geojson_sha256':digest,'environmental_api_requests':0,'site_changed':False,'actions_run_url':'https://github.com/'+os.environ.get('GITHUB_REPOSITORY','')+'/actions/runs/'+os.environ.get('GITHUB_RUN_ID','')})
    target=Path('income-group-results');target.mkdir()
    (target/'summary.json').write_text(json.dumps(report,ensure_ascii=False,separators=(',',':'),allow_nan=False),encoding='utf-8')
    write_csv(target/'groups.csv',rows);write_csv(target/'county-groups.csv',counties)
if __name__=='__main__':main()
