import argparse,csv,hashlib,io,json
from pathlib import Path
from collections import Counter
from urllib.parse import urlsplit
SOURCE='14d01550e2f9cdedb30ee59420b45cd14a1eb518'
ARCHIVE_SHA='6ba6a797a4606f6f931013c1d35d00ce1ae871d26ce0ffa45d01e49372fc6a9a'
def validate(meta,archive,rows):
    if meta.get('status')!='parsed' or meta.get('parse_issue_count')!=0:raise ValueError('Official import is not clean')
    if meta.get('income_year')!=2024 or meta.get('edition')!='initial_assessment':raise ValueError('Wrong year or edition')
    if urlsplit(meta.get('archive_url','')).hostname!='www.fia.gov.tw':raise ValueError('Unexpected official archive host')
    if meta.get('archive_sha256')!=ARCHIVE_SHA or hashlib.sha256(archive).hexdigest()!=ARCHIVE_SHA:raise ValueError('Archive snapshot differs from approved import')
    if len(rows)!=meta['comparison']['official_rows']:raise ValueError('Official row count mismatch')
    if not rows or not {'縣市','鄉鎮市區','村里','中位數'}.issubset(rows[0]):raise ValueError('Official CSV schema mismatch')
def coverage(geo,issues):
    totals=Counter();matched=Counter();missing=[]
    for f in geo['features']:
        p=f['properties'];county=p['COUNTYNAME'];totals[county]+=1
        if p['income_median'] is None:missing.append({k:p[k] for k in ['VILLCODE','COUNTYNAME','TOWNNAME','VILLNAME']})
        else:matched[county]+=1
    unmatched=Counter(str(i.get('county','')).replace('臺','台') for i in issues)
    result=[{'county':c,'boundary_features':totals[c],'matched':matched[c],'missing':totals[c]-matched[c],'coverage':matched[c]/totals[c],'unmatched_income_rows':unmatched[c.replace('臺','台')]} for c in sorted(totals)]
    return result,missing
def main():
    from build_income_map import convert,join_income
    p=argparse.ArgumentParser();p.add_argument('--artifact',required=True);p.add_argument('--geometry',required=True);a=p.parse_args()
    root=Path(a.artifact);meta=json.loads((root/'official-source.json').read_text(encoding='utf-8'))
    archive=(root/'official-html.zip').read_bytes();csvraw=(root/'official-2024-candidate.csv').read_bytes();rows=list(csv.DictReader(io.StringIO(csvraw.decode('utf-8-sig'))));validate(meta,archive,rows)
    raw=(Path(a.geometry)/'docs/map/cunli.json').read_bytes();geo,objname=convert(json.loads(raw));geo,q,issues=join_income(geo,rows)
    counties,missing=coverage(geo,issues)
    q.update({'income_source':'official_fia_direct','income_year':2024,'income_edition':meta['edition'],'income_published_date':meta['published_date'],'income_unit':meta['unit'],'official_page':meta['official_page'],'official_archive_url':meta['archive_url'],'official_archive_sha256':ARCHIVE_SHA,'income_csv_sha256':hashlib.sha256(csvraw).hexdigest(),'geometry_source_repository':'kiang/salary','geometry_source_commit':SOURCE,'geometry_sha256':hashlib.sha256(raw).hexdigest(),'topology_object':objname,'county_coverage':counties,'missing_boundary_features':len(missing),'alias_rules_applied':False,'site_deployed':False})
    target=Path('official-income-site')
    if target.exists():raise ValueError('Output exists')
    target.mkdir()
    for filename,data in [('income.geojson',geo),('quality.json',q),('issues.json',issues),('missing-villages.json',missing)]: (target/filename).write_text(json.dumps(data,ensure_ascii=False,allow_nan=False),encoding='utf-8')
    (target/'official-income.csv').write_bytes(csvraw);(target/'source.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2),encoding='utf-8')
    page='''<!doctype html><html lang="zh-Hant"><meta charset="utf-8"><title>官方所得底圖</title><link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"><script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script><p>財政部直接下載｜2024所得・初步核定｜圖資年代仍待核對｜尚未加入環境圖層</p><p>灰色為缺值，綠色分級為≤400、400–600、600–800、800–1000、>1000千元。<a href="quality.json">品質報告</a>／<a href="issues.json">未配對所得</a>／<a href="missing-villages.json">缺所得圖形</a></p><div id="map" style="height:80vh"></div><script>const m=L.map('map',{preferCanvas:true}).setView([23.7,120.6],7);L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',{attribution:'© OpenStreetMap contributors'}).addTo(m);fetch('income.geojson').then(r=>{if(!r.ok)throw Error('載入失敗');return r.json()}).then(g=>L.geoJSON(g,{style:f=>{const v=f.properties.income_median;return{color:'#777',weight:.4,fillOpacity:.65,fillColor:v===null?'#aaa':['#edf8e9','#bae4b3','#74c476','#31a354','#006d2c'][[400,600,800,1000].filter(c=>v>c).length]}},onEachFeature:(f,l)=>{const p=f.properties,e=document.createElement('div');e.textContent=[p.COUNTYNAME,p.TOWNNAME,p.VILLNAME,'官方所得中位數：',p.income_median===null?'未配對':p.income_median+'千元'].join(' ');l.bindPopup(e)}}).addTo(m)).catch(e=>{const p=document.createElement('p');p.textContent=e.message;document.body.append(p)});</script></html>'''
    (target/'index.html').write_text(page,encoding='utf-8')
    reports=Path('reports/income');reports.mkdir(parents=True,exist_ok=True)
    for filename,data in [('official-map-quality.json',q),('official-map-issues.json',issues),('official-map-missing.json',missing)]: (reports/filename).write_text(json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    print(json.dumps(q,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
