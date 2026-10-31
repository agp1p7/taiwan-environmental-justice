import argparse,hashlib,json,os,shutil
from pathlib import Path
from datetime import datetime,timezone
RUN=41216419651
FILES=('index.html','income.geojson','soil.geojson','quality.json','income-quality.json','UPSTREAM-LICENSE.txt','classification-quality.json')
METRICS=('air_records','water_records','waste_records')
def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def prepare():
    root=Path('category-release-source');source=root/'integrated-preview';target=Path('environment-preview')
    a=json.loads((root/'reports/environment/category-browser-acceptance.json').read_text(encoding='utf-8'))
    if a.get('status')!='passed' or len(a.get('checks',[]))!=12 or set(a.get('tested_category_metrics',[]))!=set(METRICS):raise ValueError('Candidate acceptance mismatch')
    if a.get('actions_run_url')!='https://github.com/agp1p7/taiwan-environmental-justice/actions/runs/'+str(RUN):raise ValueError('Candidate run mismatch')
    if not all((source/name).is_file() for name in FILES):raise ValueError('Required public asset missing')
    c=json.loads((source/'classification-quality.json').read_text(encoding='utf-8'))
    q=json.loads((source/'quality.json').read_text(encoding='utf-8'))
    if c.get('source_run_id')!=41196332873 or c.get('source_rows')!=432466 or c.get('matched_rows')!=256597:raise ValueError('Source counts mismatch')
    if c['source_clean_csv_sha256']!=q['datasets']['EMS_S_01']['clean_csv_sha256']:raise ValueError('Source checksum mismatch')
    if any(set(c['categories'][k]['observed_flag_values'])!={'0','1'} for k in ('air','water','waste')):raise ValueError('Unreviewed classification values')
    geo=json.loads((source/'income.geojson').read_text(encoding='utf-8'))
    for k in ('air','water','waste'):
        if sum(f['properties'][k+'_records'] or 0 for f in geo['features'])!=c['categories'][k]['counts']['matched_yes']:raise ValueError('Category reconciliation mismatch')
    old=json.loads((target/'income.geojson').read_text(encoding='utf-8'))
    if len(old['features'])!=len(geo['features']):raise ValueError('Boundary count changed')
    for before,after in zip(old['features'],geo['features']):
        if before['geometry']!=after['geometry'] or any(after['properties'].get(k)!=v for k,v in before['properties'].items()):raise ValueError('Existing geometry or metrics changed')
    for name in ('soil.geojson','income-quality.json','UPSTREAM-LICENSE.txt'):
        if digest(source/name)!=digest(target/name):raise ValueError('Unapproved source asset change')
    text=(source/'index.html').read_text(encoding='utf-8')
    old_notice='三分類候選預覽（尚未發布至網站）。'
    if text.count(old_notice)!=1 or any(text.count('value="'+k+'"')!=1 for k in METRICS):raise ValueError('Candidate UI mismatch')
    for name in FILES:
        data=(source/name).read_bytes()
        if name=='index.html':data=text.replace(old_notice,'三分類資料審閱預覽（非完成版）。').encode('utf-8')
        elif name in ('quality.json','classification-quality.json'):
            obj=json.loads(data);obj['source_candidate_site_deployed']=obj.pop('site_deployed',False);obj['publication_kind']='category_review_preview'
            data=json.dumps(obj,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode('utf-8')
        if len(data)>90*1024*1024:raise ValueError('Public file exceeds size safety limit')
        (target/name).write_bytes(data)
    manifest={'prepared_at_utc':datetime.now(timezone.utc).isoformat(),'source_run_id':RUN,'artifact_name':'environmental-category-candidate','candidate_browser_acceptance':'passed','publication_kind':'category_review_preview','homepage_modified':False,'raw_csv_published':False,'public_files_sha256':{name:digest(target/name) for name in FILES}}
    (target/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
def stage():
    site=Path('_site');(site/'environment-preview').mkdir(parents=True,exist_ok=True)
    shutil.copyfile('index.html',site/'index.html')
    for name in FILES+('manifest.json',):shutil.copyfile(Path('environment-preview')/name,site/'environment-preview'/name)
    (site/'.nojekyll').touch()
    if digest(site/'index.html')!=digest(Path('index.html')):raise ValueError('Homepage changed')
def record():
    url=os.environ.get('PAGES_URL','')
    if not url.startswith('https://'):raise ValueError('Missing actual deployment URL')
    site=Path('_site');m=json.loads((site/'environment-preview/manifest.json').read_text(encoding='utf-8'))
    report={'status':'deployed_category_review_preview','deployed_at_utc':datetime.now(timezone.utc).isoformat(),'preview_url':url.rstrip('/')+'/environment-preview/','homepage_url':url,'source_candidate_run_id':RUN,'homepage_sha256':digest(site/'index.html'),'public_files_sha256':m['public_files_sha256'],'environmental_api_requests':0,'current_regulatory_status_verified':False,'base_map_tiles_network_verified':False,'public_browser_report':'reports/deployment/category-public-browser-acceptance.json'}
    path=Path('reports/deployment/category-preview.json');path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['prepare','stage','record']);a=p.parse_args();{'prepare':prepare,'stage':stage,'record':record}[a.mode]()
