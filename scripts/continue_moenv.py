import hashlib,json,os
from collections import defaultdict
from datetime import datetime,timezone
from pathlib import Path
from download_moenv_checkpoint import load,save,advance,fetch
def duplicate_audit(root,entry):
    groups=defaultdict(list)
    for page in entry['pages']:
        for row in json.loads((root/page['file']).read_text(encoding='utf-8')):
            normalized={str(k).lower():v for k,v in row.items()}
            site=str(normalized.get('site_id') or '').strip()
            if site:groups[site].append(row)
    result=[]
    for site,rows in groups.items():
        if len(rows)<2:continue
        encoded=[json.dumps(r,sort_keys=True,ensure_ascii=False,allow_nan=False) for r in rows]
        hashes=[hashlib.sha256(s.encode('utf-8')).hexdigest() for s in encoded]
        fields=sorted(set().union(*(r.keys() for r in rows)))
        differing=[k for k in fields if len({json.dumps([k in r,r.get(k)],sort_keys=True,ensure_ascii=False) for r in rows})>1]
        status_fields={k:sorted({json.dumps(r.get(k),ensure_ascii=False,sort_keys=True) for r in rows}) for k in fields if any(part in k.lower() for part in ('status','date','release','cancel'))}
        result.append({'site_id':site,'rows':len(rows),'unique_full_records':len(set(hashes)),'identical_full_record_excess':len(rows)-len(set(hashes)),'differing_fields':differing,'record_sha256':hashes,'status_and_date_variants':status_fields,'records_merged':False})
    return {'dataset':'EMS_S_07','duplicate_groups':result,'status_interpretation_verified':False,'records_merged':False}
def main():
    root=Path('environment-snapshot');state=load(root)
    if state['datasets']['EMS_S_01']['next_offset']<140000 or not state['datasets']['EMS_S_07']['complete']:raise SystemExit('Expected saved progress and completed soil pagination; refusing restart')
    audit=duplicate_audit(root,state['datasets']['EMS_S_07'])
    save(Path('reports/environment/soil-duplicates.json'),audit)
    report={'checked_at_utc':datetime.now(timezone.utc).isoformat(),'request_budget_by_dataset':{'EMS_S_01':100,'EMS_S_07':0},'page_size':1000,'automatic_retries':False,'credentials_saved':False,'live_map_changed':False,'datasets':[]}
    key=os.environ.get('MOENV_API_KEY','').strip()
    if not key:raise SystemExit('Missing API secret; no API requests made')
    for dataset,budget in report['request_budget_by_dataset'].items():report['datasets'].append(advance(root,state,dataset,fetch,key,budget=budget))
    report['actual_http_requests']=sum(d['actual_http_requests'] for d in report['datasets'])
    report['status']='failed_or_partial' if any(d['status']=='failed' for d in report['datasets']) else ('complete_to_empty_page' if all(d['status']=='complete_to_empty_page' for d in report['datasets']) else 'paused_with_checkpoint')
    save(Path('reports/environment/download-quality.json'),report)
    print(json.dumps(report,ensure_ascii=False))
    if report['status']=='failed_or_partial':raise SystemExit(1)
if __name__=='__main__':main()
