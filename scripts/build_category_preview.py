import csv,hashlib,io,json,shutil
from collections import Counter
from pathlib import Path
source=Path('category-build-source');target=Path('integrated-preview')
q=json.loads(Path('environment-preview/quality.json').read_text(encoding='utf-8'))
if q['source_environment_head_sha']!='8b03343b4261e1f7b07870fe68d8f8702677d639':raise ValueError('Unexpected source version')
raw=(source/'EMS_S_01-clean.csv').read_bytes()
if hashlib.sha256(raw).hexdigest()!=q['datasets']['EMS_S_01']['clean_csv_sha256']:raise ValueError('Clean CSV checksum mismatch')
geo=json.loads(Path('environment-preview/income.geojson').read_text(encoding='utf-8'))
valid={str(f['properties']['VILLCODE']) for f in geo['features'] if f['properties'].get('ems01_records') is not None}
fields={'air':'isair','water':'iswater','waste':'iswaste'}
observed={k:Counter() for k in fields};summary={k:Counter() for k in fields}
yes={k:Counter() for k in fields};unknown={k:Counter() for k in fields}
def classify(value):
    value=str(value or '').strip().lower()
    return 'yes' if value in ('1','y','yes','true','是') else 'no' if value in ('0','n','no','false','否') else 'unknown'
reader=csv.DictReader(io.StringIO(raw.decode('utf-8-sig')))
if not set(fields.values()).issubset(reader.fieldnames or []):raise ValueError('Classification columns missing')
rows=0;matched=0
for row in reader:
    rows+=1;code=row['villcode'];inside=row['spatial_status']=='matched'
    if inside:
        if code not in valid:raise ValueError('Matched code absent from valid boundary set')
        matched+=1
    for k,field in fields.items():
        value=str(row.get(field) or '').strip();status=classify(value)
        observed[k][value if len(value)<=16 else '[long-value-redacted]']+=1
        summary[k][status]+=1
        if inside:
            summary[k]['matched_'+status]+=1
            if status=='yes':yes[k][code]+=1
            elif status=='unknown':unknown[k][code]+=1
expected=q['datasets']['EMS_S_01']['counts']
if rows!=expected['unique_full_rows'] or matched!=expected['spatial_matched']:raise ValueError('Source counts mismatch')
for f in geo['features']:
    p=f['properties'];code=str(p['VILLCODE'])
    for k in fields:
        p[k+'_records']=yes[k].get(code,0) if code in valid else None
        p[k+'_unknown_records']=unknown[k].get(code,0) if code in valid else None
for k in fields:
    if sum(yes[k].values())!=summary[k]['matched_yes']:raise ValueError('Category reconciliation failed')
report={'source_run_id':41196332873,'environmental_api_requests':0,'site_deployed':False,'source_rows':rows,'matched_rows':matched,'source_clean_csv_sha256':hashlib.sha256(raw).hexdigest(),'categories':{k:{'observed_flag_values':dict(observed[k]),'counts':dict(summary[k])} for k in fields},'yes_values':['1','y','yes','true','是'],'no_values':['0','n','no','false','否'],'all_other_values':'unknown_not_assumed_no','record_counts_not_unique_businesses':True,'categories_can_overlap':True,'current_regulatory_status_verified':False,'coordinate_or_boundary_repairs_applied':False}
if target.exists():raise ValueError('Candidate directory already exists')
target.mkdir()
for name in ('soil.geojson','income-quality.json','UPSTREAM-LICENSE.txt'):
    shutil.copyfile(Path('environment-preview')/name,target/name)
text=Path('environment-preview/index.html').read_text(encoding='utf-8')
options='<option value="air_records">空污管理分類配對紀錄數（含歷史）</option><option value="water_records">水污管理分類配對紀錄數（含歷史）</option><option value="waste_records">廢棄物管理分類配對紀錄數（含歷史）</option>'
old='<option value="ems01_records">'
if text.count(old)!=1:raise ValueError('Metric selector changed')
text=text.replace(old,options+old)
old="'管理紀錄數：'+value(p.ems01_records),"
extra="'空污分類紀錄數：'+value(p.air_records),'水污分類紀錄數：'+value(p.water_records),'廢棄物分類紀錄數：'+value(p.waste_records),'分類不明（空／水／廢）：'+[value(p.air_unknown_records),value(p.water_unknown_records),value(p.waste_unknown_records)].join('/'),"
if text.count(old)!=1:raise ValueError('Village popup changed')
text=text.replace(old,old+extra)
old='<summary>圖例與資料限制</summary>'
if text.count(old)!=1:raise ValueError('Legend changed')
text=text.replace(old,old+'<p>三分類為管理旗標的已識別紀錄數，包含歷史資料，不是AQI、排放量、污染強度或現行事業數。類別可重疊，不可相加。空白或不識別旗標另列分類不明；0筆已識別紀錄不代表沒有該類事業。<a href="classification-quality.json">分類值與品質報告</a></p>')
text=text.replace('資料品質審閱預覽（非完成版）。','三分類候選預覽（尚未發布至網站）。')
(target/'index.html').write_text(text,encoding='utf-8')
q.update({'site_deployed':False,'publication_kind':'category_candidate_not_deployed','category_metrics_available':[k+'_records' for k in fields]})
for name,obj in [('income.geojson',geo),('quality.json',q),('classification-quality.json',report)]:
    (target/name).write_text(json.dumps(obj,ensure_ascii=False,separators=(',',':'),allow_nan=False),encoding='utf-8')
out=Path('reports/environment/classification-quality.json');out.parent.mkdir(parents=True,exist_ok=True)
out.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
