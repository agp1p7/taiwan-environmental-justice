import argparse,csv,hashlib,io,json,math,re,unicodedata,zipfile
from pathlib import Path
from urllib.request import Request,build_opener,HTTPRedirectHandler
from urllib.parse import urljoin,urlsplit
from datetime import datetime,timezone
from bs4 import BeautifulSoup
PAGE='https://www.fia.gov.tw/singlehtml/43?cntId=4c3fc1e8a7c545179280b6a50a27cd35'
COUNTIES={'A':'臺北市','B':'臺中市','C':'基隆市','D':'臺南市','E':'高雄市','F':'新北市','G':'宜蘭縣','H':'桃園市','I':'嘉義市','J':'新竹縣','K':'苗栗縣','M':'南投縣','N':'彰化縣','O':'新竹市','P':'雲林縣','Q':'嘉義縣','T':'屏東縣','U':'花蓮縣','V':'臺東縣','W':'金門縣','X':'澎湖縣','Z':'連江縣'}
FIELDS=['納稅單位','綜合所得總額','平均數','中位數','第一分位數','第三分位數','標準差','變異係數']
HEAD=['縣市','鄉鎮市區','村里']+FIELDS
def norm(s):return re.sub(r'\s+','',unicodedata.normalize('NFKC',str(s or ''))).replace('臺','台')
def official(url):
    p=urlsplit(url)
    if p.scheme!='https' or p.hostname not in ('www.fia.gov.tw','fia.gov.tw'):raise ValueError('Nonofficial or non-HTTPS URL')
    return url
class SafeRedirect(HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        official(newurl)
        return super().redirect_request(req,fp,code,msg,headers,newurl)
def download(url,maximum):
    with build_opener(SafeRedirect()).open(Request(official(url),headers={'User-Agent':'TaiwanEJ-OfficialIncome/1.0'}),timeout=90) as response:
        official(response.url);body=response.read(maximum+1)
    if len(body)>maximum:raise ValueError('Download exceeds safety limit')
    return body
def find_zip(page):
    links=set()
    for a in BeautifulSoup(page,'html.parser').find_all('a',href=True):
        label=a.get_text(' ',strip=True)+' '+str(a.get('title',''))
        if '113' in label and 'HTML' in label.upper():links.add(official(urljoin(PAGE,a['href'])))
    if len(links)!=1:raise ValueError('Cannot identify exactly one official 113 HTML ZIP link')
    return links.pop()
def parse_table(raw,county):
    soup=BeautifulSoup(raw,'html.parser');text=norm(soup.get_text())
    if not all(s in text for s in ['165','113','中位數','千元',norm(county)]):raise ValueError('Official table title, year, unit or county validation failed')
    rows=[];issues=[];skipped=0;lasttown=''
    for line,tr in enumerate(soup.find_all('tr'),1):
        cells=tr.find_all('td',recursive=False)
        if len(cells)!=12:continue
        c=[re.sub(r'\s+','',td.get_text(' ',strip=True)) for td in cells]
        town,village=c[1],c[2]
        if village in ('村里','村里別',''):continue
        if village in ('合計','小計','總計','其他'):skipped+=1;continue
        if town:lasttown=town
        if not lasttown:issues.append({'line':line,'reason':'missing_town'});continue
        try:
            nums=[float(unicodedata.normalize('NFKC',v).replace(',','')) for v in c[3:11]]
            if not all(math.isfinite(v) and v>=0 for v in nums):raise ValueError
            if nums[0]!=int(nums[0]) or not nums[4]<=nums[3]<=nums[5]:raise ValueError
        except ValueError:
            issues.append({'line':line,'reason':'invalid_numeric_or_quantile','town':lasttown,'village':village});continue
        row=dict(zip(HEAD,[county,lasttown,village]+nums));row['納稅單位']=int(nums[0]);rows.append(row)
    if not rows:raise ValueError('No data rows recognized in official HTML table')
    return rows,issues,skipped
def key(r):return tuple(norm(r[k]) for k in HEAD[:3])
def compare(a,b):
    def index(rows):
        pool={}
        for r in rows:
            k=key(r)
            if k in pool:raise ValueError('Duplicate name key: '+str(k))
            pool[k]=r
        return pool
    left,right=index(a),index(b);diff=[];same=0;common=set(left)&set(right)
    for k in sorted(common):
        changes={}
        for field in FIELDS:
            x=float(str(left[k][field]).replace(',',''));y=float(str(right[k][field]).replace(',',''))
            if not(math.isfinite(x) and math.isfinite(y)):raise ValueError('Nonfinite comparison value')
            if abs(x-y)>1e-8:changes[field]={'official':x,'mirror':y}
        if changes:diff.append({'name':k,'changes':changes})
        else:same+=1
    return {'official_rows':len(a),'mirror_rows':len(b),'common_name_keys':len(common),'all_numeric_fields_equal':same,'numeric_difference_rows':len(diff),'official_only_rows':len(set(left)-set(right)),'mirror_only_rows':len(set(right)-set(left))},{'numeric_differences':diff,'official_only':[left[k] for k in sorted(set(left)-set(right))],'mirror_only':[right[k] for k in sorted(set(right)-set(left))]}
def main():
    parser=argparse.ArgumentParser();parser.add_argument('--mirror',required=True);args=parser.parse_args()
    output=Path('official-income');output.mkdir(exist_ok=True);reportpath=Path('reports/income');reportpath.mkdir(parents=True,exist_ok=True)
    summary={'status':'started','official_page':PAGE,'income_year':2024,'roc_year':113,'edition':'initial_assessment','published_date':'2026-06-30','unit':'thousand_TWD','live_data_replaced':False,'retrieved_at_utc':datetime.now(timezone.utc).isoformat()}
    try:
        page=download(PAGE,10000000);(output/'source-page.html').write_bytes(page);url=find_zip(page);raw=download(url,250000000);(output/'official-html.zip').write_bytes(raw)
        summary.update({'archive_url':url,'archive_sha256':hashlib.sha256(raw).hexdigest(),'page_sha256':hashlib.sha256(page).hexdigest()})
        allrows=[];parsing=[];members={};county_stats=[]
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            for name in archive.namelist():
                match=re.search(r'(?:^|/)113_165-([A-Z])\.html?$',name,re.I)
                if match:
                    region=match[1].upper()
                    if region in members:raise ValueError('Duplicate table 165 region '+region)
                    members[region]=name
            if set(members)!=set(COUNTIES):raise ValueError('Official table region set differs from expected 22 counties')
            for region,county in COUNTIES.items():
                member=members[region]
                if archive.getinfo(member).file_size>10000000:raise ValueError('Table too large')
                content=archive.read(member);rows,issues,skipped=parse_table(content,county);allrows.extend(rows)
                parsing.extend(dict(i,county=county) for i in issues);county_stats.append({'county':county,'rows':len(rows),'skipped_totals':skipped,'issues':len(issues),'member':member,'sha256':hashlib.sha256(content).hexdigest()})
                (output/(region+'.html')).write_bytes(content)
        mirror_raw=Path(args.mirror).read_bytes();mirror=list(csv.DictReader(io.StringIO(mirror_raw.decode('utf-8-sig'))));comparison,differences=compare(allrows,mirror)
        with (output/'official-2024-candidate.csv').open('w',encoding='utf-8-sig',newline='') as f:
            writer=csv.DictWriter(f,fieldnames=HEAD);writer.writeheader();writer.writerows(allrows)
        summary.update({'status':'parsed_with_issues' if parsing else 'parsed','county_stats':county_stats,'parse_issue_count':len(parsing),'comparison':comparison,'mirror_sha256':hashlib.sha256(mirror_raw).hexdigest(),'candidate_only':True})
        (reportpath/'official-differences.json').write_text(json.dumps({'parse_issues':parsing,**differences},ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    except Exception as error:
        summary.update({'status':'failed','error_type':type(error).__name__,'error':str(error)[:1000]})
    (reportpath/'official-source.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    (output/'official-source.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    print(json.dumps(summary,ensure_ascii=False,indent=2,allow_nan=False))
    if summary['status']!='parsed':raise SystemExit(1)
if __name__=='__main__':main()
