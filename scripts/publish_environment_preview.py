import argparse,hashlib,json,os,shutil
from pathlib import Path
from datetime import datetime,timezone
FILES=('index.html','income.geojson','soil.geojson','quality.json','income-quality.json','UPSTREAM-LICENSE.txt')
def prepare(source,dest):
    acceptance=json.loads((source/'browser-acceptance.json').read_text(encoding='utf-8'))
    if acceptance.get('status')!='passed' or len(acceptance.get('checks',[]))!=12:raise ValueError('Browser acceptance not passed')
    if acceptance.get('actions_run_url')!='https://github.com/agp1p7/taiwan-environmental-justice/actions/runs/41196332873':raise ValueError('Unexpected acceptance source')
    q=json.loads((source/'quality.json').read_text(encoding='utf-8'))
    if q.get('source_environment_head_sha')!='8b03343b4261e1f7b07870fe68d8f8702677d639' or q.get('source_income_head_sha')!='3a063816ed989a3b0f947283d3b68bae24060e40':raise ValueError('Unexpected data provenance')
    if not all((source/name).is_file() for name in FILES):raise ValueError('Public allowlist source missing')
    if dest.exists():shutil.rmtree(dest)
    dest.mkdir(parents=True)
    for name in FILES:
        data=(source/name).read_bytes()
        if name=='index.html':
            text=data.decode('utf-8')
            if text.count('未部署驗證版。')!=1:raise ValueError('Unexpected preview notice')
            data=text.replace('未部署驗證版。','資料品質審閱預覽（非完成版）。').encode('utf-8')
        elif name.endswith(('.json','.geojson')):
            obj=json.loads(data)
            if name=='quality.json':
                obj['source_artifact_site_deployed']=obj.pop('site_deployed',False)
                obj['publication_kind']='quality_review_preview'
                obj['not_for_current_pollution_or_exposure_claims']=True
            data=json.dumps(obj,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode('utf-8')
        if len(data)>90*1024*1024:raise ValueError('Public file exceeds repository safety size')
        (dest/name).write_bytes(data)
    manifest={'prepared_at_utc':datetime.now(timezone.utc).isoformat(),'source_run_id':41196332873,'artifact_name':'environmental-integration-preview','browser_acceptance':'passed','publication_kind':'quality_review_preview','private_raw_files_published':False,'homepage_modified':False,'public_files_sha256':{name:hashlib.sha256((dest/name).read_bytes()).hexdigest() for name in FILES}}
    (dest/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
def record_deployment(site,path):
    page_url=os.environ.get('PAGES_URL','').strip()
    if not page_url.startswith('https://'):raise ValueError('Missing actual deployment URL')
    manifest=json.loads((site/'environment-preview/manifest.json').read_text(encoding='utf-8'))
    report={'deployed_at_utc':datetime.now(timezone.utc).isoformat(),'status':'deployed_review_preview','homepage_url':page_url,'preview_url':page_url.rstrip('/')+'/environment-preview/','source_run_id':manifest['source_run_id'],'homepage_sha256':hashlib.sha256((site/'index.html').read_bytes()).hexdigest(),'public_files_sha256':manifest['public_files_sha256'],'environmental_api_requests':0,'boundary_vintage_verified':False,'current_regulatory_status_verified':False,'private_raw_files_published':False}
    path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
def main():
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['prepare','record']);a=p.parse_args()
    if a.mode=='prepare':prepare(Path('approved-preview'),Path('environment-preview'))
    else:record_deployment(Path('_site'),Path('reports/deployment/environment-preview.json'))
if __name__=='__main__':main()
