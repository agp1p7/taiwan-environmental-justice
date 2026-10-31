import argparse,csv,hashlib,json,math,shutil
from collections import Counter
from pathlib import Path
from datetime import datetime,timezone
from shapely.geometry import Point,shape
from shapely.strtree import STRtree
from download_moenv_checkpoint import load,save
DATASETS={'EMS_S_01':('emsno','wgs84lon','wgs84lat',454333),'EMS_S_07':('site_id','wgs84_lng','wgs84_lat',8257)}
def present(value):return str('' if value is None else value).strip().lower() not in ('','null','none','nan','--','-')
def soil_status(row):
    if present(row.get('deanno_no')) or present(row.get('deanno_date')):return 'release_information_present'
    if present(row.get('anno_no')) or present(row.get('anno_date')):return 'announcement_without_release_information'
    return 'announcement_information_unknown'
def coordinates(row,lonkey,latkey):
    if not present(row.get(lonkey)) or not present(row.get(latkey)):return None,'missing_coordinates'
    try:
        lon=float(row[lonkey]);lat=float(row[latkey])
        if not math.isfinite(lon) or not math.isfinite(lat) or not -180<=lon<=180 or not -90<=lat<=90:raise ValueError()
        if lon==0 or lat==0:return None,'zero_coordinates'
        return (lon,lat),None
    except (ValueError,TypeError):return None,'invalid_coordinates'
class VillageIndex:
    def __init__(self,geo):
        self.geometries=[];self.codes=[];self.unnamed=0;self.invalid=0
        for feature in geo['features']:
            p=feature['properties']
            if not str(p.get('VILLNAME') or '').strip():self.unnamed+=1;continue
            geometry=shape(feature['geometry'])
            if geometry.is_empty or not geometry.is_valid or geometry.geom_type not in ('Polygon','MultiPolygon'):self.invalid+=1;continue
            self.geometries.append(geometry);self.codes.append(str(p['VILLCODE']))
        if not self.geometries:raise ValueError('No valid named boundaries')
        self.tree=STRtree(self.geometries)
    def match(self,coords):
        point=Point(*coords);hits=self.tree.query(point,predicate='intersects')
        if len(hits)==1 and self.geometries[int(hits[0])].contains(point):return self.codes[int(hits[0])],'matched'
        return None,'boundary_or_overlap' if len(hits) else 'outside_named_boundaries'
def process(root,entry,dataset,index,target):
    idkey,lonkey,latkey,expected=DATASETS[dataset]
    if not entry['complete'] or entry['next_offset']!=expected:raise ValueError('Unexpected or incomplete source snapshot')
    counts=Counter();ids=Counter();fields=set();seen=set();village=Counter();statuses=Counter();points=[]
    path=target/(dataset+'-clean.csv')
    columns=['record_sha256','source_id','longitude','latitude','villcode','spatial_status','announcement_status','isair','iswater','iswaste']
    with path.open('w',encoding='utf-8-sig',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=columns);writer.writeheader()
        for page in entry['pages']:
            rows=json.loads((root/page['file']).read_text(encoding='utf-8'))
            for original in rows:
                counts['input_rows']+=1
                digest=hashlib.sha256(json.dumps(original,ensure_ascii=False,sort_keys=True,allow_nan=False).encode('utf-8')).hexdigest()
                if digest in seen:counts['exact_duplicate_rows_removed']+=1;continue
                seen.add(digest);counts['unique_full_rows']+=1
                row={str(k).lower():v for k,v in original.items()}
                if len(row)!=len(original):raise ValueError('Case-folded field collision')
                fields.update(row)
                if not {idkey,lonkey,latkey}.issubset(row):raise ValueError('Required source fields absent')
                source_id=str(row.get(idkey) or '').strip();coords,issue=coordinates(row,lonkey,latkey)
                status=soil_status(row) if dataset=='EMS_S_07' else 'current_management_status_not_interpreted'
                statuses[status]+=1
                if source_id:ids[source_id]+=1
                else:counts['missing_source_id']+=1
                code=None
                if issue:spatial=issue
                elif not source_id:spatial='missing_source_id'
                else:code,spatial=index.match(coords)
                counts['spatial_'+spatial]+=1
                if code:village[code]+=1
                writer.writerow({'record_sha256':digest,'source_id':source_id,'longitude':coords[0] if coords else '', 'latitude':coords[1] if coords else '', 'villcode':code or '', 'spatial_status':spatial,'announcement_status':status,**{k:row.get(k,'') for k in ('isair','iswater','iswaste')}})
                if dataset=='EMS_S_07' and coords and source_id:
                    points.append({'type':'Feature','geometry':{'type':'Point','coordinates':list(coords)},'properties':{'source_id':source_id,'villcode':code,'spatial_status':spatial,'announcement_status':status}})
    if counts['input_rows']!=expected:raise ValueError('Source row count mismatch')
    report={'counts':dict(counts),'announcement_status_counts':dict(statuses),'distinct_nonempty_source_ids':len(ids),'source_id_groups_with_multiple_nonidentical_records':sum(v>1 for v in ids.values()),'observed_fields':sorted(fields),'clean_csv_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'source_pages':len(entry['pages']),'records_are_not_unique_business_or_current_pollution_counts':True}
    return report,village,points
def main():
    p=argparse.ArgumentParser();p.add_argument('--environment',required=True);p.add_argument('--income',required=True);a=p.parse_args()
    root=Path(a.environment);income=Path(a.income);state=load(root)
    iq=json.loads((income/'quality.json').read_text(encoding='utf-8'))
    if iq.get('income_year')!=2024 or iq.get('scoped_name_fixes_applied')!=11:raise ValueError('Unexpected income artifact')
    raw=(income/'income.geojson').read_bytes();geo=json.loads(raw)
    if len(geo['features'])!=iq['boundary_features']:raise ValueError('Boundary feature mismatch')
    index=VillageIndex(geo);target=Path('integrated-preview')
    if target.exists():raise ValueError('Output already exists')
    shutil.copytree(income,target);reports={};village_counts={};soil=[]
    for dataset in DATASETS:
        report,counts,points=process(root,state['datasets'][dataset],dataset,index,target)
        reports[dataset]=report;village_counts[dataset]=counts
        if dataset=='EMS_S_07':soil=points
    valid=set(index.codes)
    for feature in geo['features']:
        props=feature['properties'];code=str(props['VILLCODE'])
        props['ems01_records']=village_counts['EMS_S_01'].get(code,0) if code in valid else None
        props['soil_records']=village_counts['EMS_S_07'].get(code,0) if code in valid else None
    q={'checked_at_utc':datetime.now(timezone.utc).isoformat(),'datasets':reports,'unnamed_boundary_features_excluded':index.unnamed,'invalid_named_boundary_features_excluded':index.invalid,'valid_named_boundary_features':len(valid),'income_artifact_geojson_sha256':hashlib.sha256(raw).hexdigest(),'source_environment_head_sha':'8b03343b4261e1f7b07870fe68d8f8702677d639','source_income_head_sha':'3a063816ed989a3b0f947283d3b68bae24060e40','environmental_api_requests':0,'original_source_files_modified':False,'boundary_vintage_verified':False,'national_validity_verified':False,'snapshot_consistency_verified':False,'current_regulatory_status_verified':False,'environment_layers_loaded':True,'site_deployed':False,'boundary_or_overlapping_points_not_force_assigned':True,'metric_definition':'exact-full-row-deduplicated records with a source ID and valid nonzero coordinates strictly inside one named valid polygon; not unique businesses, active sites, exposure or risk'}
    save(target/'income.geojson',geo);save(target/'soil.geojson',{'type':'FeatureCollection','features':soil});save(target/'income-quality.json',iq);save(target/'quality.json',q)
    save(Path('reports/environment/integration-quality.json'),q)
    shutil.copyfile('templates/environment-preview.html',target/'index.html')
    print(json.dumps(q,ensure_ascii=False))
if __name__=='__main__':main()
