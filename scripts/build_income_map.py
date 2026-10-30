import argparse,csv,hashlib,io,json,math,re,unicodedata
from pathlib import Path
from collections import defaultdict,Counter
SOURCE='14d01550e2f9cdedb30ee59420b45cd14a1eb518'
def norm(v):return re.sub(r'\s+','',unicodedata.normalize('NFKC',str(v or ''))).replace('臺','台')
def convert(t):
 if t.get('type')!='Topology' or len(t.get('objects',{}))!=1:raise ValueError('Expected single-object Topology')
 name,obj=next(iter(t['objects'].items()));tr=t.get('transform');arcs=[]
 for raw in t.get('arcs',[]):
  x=y=0;line=[]
  for p in raw:
   if tr:x+=p[0];y+=p[1];point=[x*tr['scale'][0]+tr['translate'][0],y*tr['scale'][1]+tr['translate'][1]]
   else:point=p[:2]
   if len(point)!=2 or not all(isinstance(v,(int,float)) and math.isfinite(v) for v in point) or not(-180<=point[0]<=180 and -90<=point[1]<=90):raise ValueError('Invalid geographic coordinates')
   line.append(point)
  arcs.append(line)
 def ring(ids):
  line=[]
  for i in ids:
   if not isinstance(i,int):raise ValueError('Invalid arc')
   j=i if i>=0 else ~i
   if not 0<=j<len(arcs):raise ValueError('Arc out of range')
   part=arcs[j] if i>=0 else list(reversed(arcs[j]))
   if line and part and line[-1]!=part[0]:raise ValueError('Disconnected arcs')
   line.extend(part if not line else part[1:])
  if len(line)<4 or line[0]!=line[-1]:raise ValueError('Unclosed ring')
  return line
 gs=obj.get('geometries') if obj.get('type')=='GeometryCollection' else [obj]
 if not isinstance(gs,list):raise ValueError('Invalid collection')
 fs=[];seen=set()
 for g in gs:
  if g['type']=='Polygon':coordinates=[ring(r) for r in g['arcs']]
  elif g['type']=='MultiPolygon':coordinates=[[ring(r) for r in poly] for poly in g['arcs']]
  else:raise ValueError('Unsupported geometry')
  p=g.get('properties',{});code=str(p.get('VILLCODE','')).strip()
  if not code or code in seen or any(not str(p.get(k,'')).strip() for k in ('COUNTYNAME','TOWNNAME','VILLNAME')):raise ValueError('Invalid village properties or duplicate code')
  seen.add(code);fs.append({'type':'Feature','properties':dict(p),'geometry':{'type':g['type'],'coordinates':coordinates}})
 if not fs:raise ValueError('No features')
 return {'type':'FeatureCollection','features':fs},name
def join_income(geo,rows):
 names=defaultdict(list)
 for f in geo['features']:
  p=f['properties'];names[tuple(norm(p[k]) for k in ('COUNTYNAME','TOWNNAME','VILLNAME'))].append(str(p['VILLCODE']))
 accepted={};seen=set();blocked=set();issues=[];skipped=0
 for i,r in enumerate(rows,1):
  if norm(r.get('村里','')) in ('合計','總計','小計','其他'):skipped+=1;continue
  key=tuple(norm(r.get(k,'')) for k in ('縣市','鄉鎮市區','村里'));matches=names.get(key,[])
  if len(matches)!=1:issues.append({'row':i,'reason':'unmatched_or_ambiguous_name','county':r.get('縣市'),'town':r.get('鄉鎮市區'),'village':r.get('村里')});continue
  code=matches[0]
  if code in seen:blocked.add(code);accepted.pop(code,None);issues.append({'row':i,'reason':'duplicate_village','villcode':code});continue
  seen.add(code)
  try:
   v=float(r['中位數'].replace(',',''))
   if not math.isfinite(v) or v<0:raise ValueError
  except (ValueError,KeyError):issues.append({'row':i,'reason':'invalid_median','villcode':code});continue
  accepted[code]=v
 for code in blocked:accepted.pop(code,None)
 for f in geo['features']:
  f['properties']['income_median']=accepted.get(str(f['properties']['VILLCODE']));f['properties']['income_year']=2024
 q={'income_rows':len(rows),'boundary_features':len(geo['features']),'matched_boundary_features':len(accepted),'skipped_aggregate_rows':skipped,'issue_counts':dict(Counter(r['reason'] for r in issues)),'boundary_coverage':len(accepted)/len(geo['features']),'national_validity_verified':False,'environment_layers_loaded':False,'boundary_vintage_verified':False}
 return geo,q,issues
def main():
 p=argparse.ArgumentParser();p.add_argument('--source',required=True);p.add_argument('--output',required=True);a=p.parse_args();root=Path(a.source);dest=Path(a.output)
 if dest.exists():raise ValueError('Output exists')
 raw=(root/'docs/map/cunli.json').read_bytes();data=(root/'data/csv/2024.csv').read_bytes();geo,name=convert(json.loads(raw));rows=list(csv.DictReader(io.StringIO(data.decode('utf-8-sig'))))
 if not rows or not {'縣市','鄉鎮市區','村里','中位數'}.issubset(rows[0]):raise ValueError('Income schema mismatch')
 geo,q,issues=join_income(geo,rows);q.update({'expected_source_commit':SOURCE,'topology_object':name,'sha256':{'topology':hashlib.sha256(raw).hexdigest(),'income':hashlib.sha256(data).hexdigest()}});dest.mkdir(parents=True)
 for filename,obj in [('income.geojson',geo),('quality.json',q),('issues.json',issues)]: (dest/filename).write_text(json.dumps(obj,ensure_ascii=False,allow_nan=False),encoding='utf-8')
 page='''<!doctype html><html lang="zh-Hant"><meta charset="utf-8"><title>所得圖資驗證</title><link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"><script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script><p>2024來源所得配對驗證；圖資年代待核對；非環境風險圖。灰色未配對，綠色已配對。<a href="quality.json">品質報告</a>／<a href="issues.json">問題清單</a></p><div id="map" style="height:85vh"></div><script>const m=L.map('map',{preferCanvas:true}).setView([23.7,120.6],7);L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',{attribution:'© OpenStreetMap contributors'}).addTo(m);fetch('income.geojson').then(r=>{if(!r.ok)throw Error('載入失敗');return r.json()}).then(g=>L.geoJSON(g,{style:f=>({color:'#777',weight:.4,fillOpacity:.5,fillColor:f.properties.income_median===null?'#aaa':'#399857'}),onEachFeature:(f,l)=>{let e=document.createElement('div');e.textContent=[f.properties.COUNTYNAME,f.properties.TOWNNAME,f.properties.VILLNAME,'中位數：',f.properties.income_median===null?'未配對':f.properties.income_median+' 千元'].join(' ');l.bindPopup(e)}}).addTo(m)).catch(e=>{let p=document.createElement('p');p.textContent=e.message;document.body.append(p)});</script></html>'''
 (dest/'index.html').write_text(page,encoding='utf-8');(dest/'SOURCE.txt').write_text('Third-party source: https://github.com/kiang/salary/tree/'+SOURCE,encoding='utf-8')
 for filename in ['README.md','LICENSE.txt']:
  if (root/filename).is_file():(dest/('UPSTREAM-'+filename)).write_bytes((root/filename).read_bytes())
 print(json.dumps(q,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
