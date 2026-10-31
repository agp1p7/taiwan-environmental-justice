import argparse,hashlib,json,math
from collections import Counter,defaultdict
from pathlib import Path
from datetime import datetime,timezone
from shapely import make_valid
from shapely.geometry import shape,mapping
from shapely.validation import explain_validity
from download_moenv_checkpoint import load,save
from integrate_environment import coordinates
def numeric_pair(row):
    try:
        x=float(row.get('twd97tm2x'));y=float(row.get('twd97tm2y'))
        return math.isfinite(x) and math.isfinite(y) and x!=0 and y!=0
    except (ValueError,TypeError):return False
def repair_candidate(feature):
    geometry=shape(feature['geometry'])
    if geometry.is_valid:return None,None
    fixed=make_valid(geometry)
    usable=not fixed.is_empty and fixed.is_valid and fixed.geom_type in ('Polygon','MultiPolygon')
    props=feature['properties']
    item={k:props.get(k) for k in ('VILLCODE','COUNTYNAME','TOWNNAME','VILLNAME')}
    item.update({'invalidity':explain_validity(geometry).split('[')[0],'candidate_type':fixed.geom_type,'candidate_valid_polygonal':usable,'candidate_applied':False,'administrative_boundary_identity_verified':False})
    candidate={'type':'Feature','properties':{**props,'repair_candidate_only':True,'administrative_boundary_identity_verified':False},'geometry':mapping(fixed)} if usable else None
    return item,candidate
def main():
    p=argparse.ArgumentParser();p.add_argument('--environment',required=True);p.add_argument('--income',required=True);p.add_argument('--preview',required=True);a=p.parse_args()
    root=Path(a.environment);income=Path(a.income);target=Path(a.preview);state=load(root)
    entry=state['datasets']['EMS_S_01']
    if not entry['complete'] or entry['next_offset']!=454333:raise ValueError('Unexpected EMS source')
    counts=Counter();county=defaultdict(Counter);seen=set()
    for page in entry['pages']:
        for original in json.loads((root/page['file']).read_text(encoding='utf-8')):
            digest=hashlib.sha256(json.dumps(original,ensure_ascii=False,sort_keys=True,allow_nan=False).encode('utf-8')).hexdigest()
            if digest in seen:continue
            seen.add(digest);counts['unique_full_rows']+=1
            row={str(k).lower():v for k,v in original.items()};_,issue=coordinates(row,'wgs84lon','wgs84lat')
            if issue=='zero_coordinates':
                counts['zero_wgs84_rows']+=1;c=str(row.get('county') or '未填縣市');county[c]['zero_wgs84_rows']+=1
                key='zero_wgs84_with_finite_nonzero_twd97_pair' if numeric_pair(row) else 'zero_wgs84_without_finite_nonzero_twd97_pair'
                counts[key]+=1;county[c][key]+=1
    if counts['unique_full_rows']!=432466:raise ValueError('Unexpected deduplicated EMS count')
    raw=(income/'income.geojson').read_bytes();geo=json.loads(raw);issues=[];candidates=[];errors=[]
    for feature in geo['features']:
        if not str(feature['properties'].get('VILLNAME') or '').strip():continue
        try:
            issue,candidate=repair_candidate(feature)
            if issue:issues.append(issue)
            if candidate:candidates.append(candidate)
        except Exception as error:errors.append({'villcode':feature['properties'].get('VILLCODE'),'error_type':type(error).__name__})
    report={'checked_at_utc':datetime.now(timezone.utc).isoformat(),'coordinate_counts':dict(counts),'zero_coordinate_counts_by_declared_county':{k:dict(v) for k,v in sorted(county.items())},'invalid_boundary_issues':issues,'geometry_candidate_count':len(candidates),'geometry_candidate_errors':errors,'income_source_geojson_sha256':hashlib.sha256(raw).hexdigest(),'twd97_zone_verified':False,'coordinate_conversion_applied':False,'geometry_candidates_applied':False,'original_source_files_modified':False,'environmental_api_requests':0,'site_deployed':False,'interpretation':'Numeric TWD97 pairs are only potential recovery candidates; grid zone, units, location and administrative identity remain unverified. No conversion or boundary replacement is applied.'}
    save(target/'boundary-repair-candidates.geojson',{'type':'FeatureCollection','features':candidates})
    save(target/'quality-followup.json',report);save(Path('reports/environment/quality-followup.json'),report)
    print(json.dumps(report,ensure_ascii=False))
if __name__=='__main__':main()
