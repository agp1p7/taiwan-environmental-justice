import copy,hashlib,io,json,sys
from collections import Counter
from contextlib import redirect_stdout
from pathlib import Path
RULES=[
('臺中市','大安區','龜売里','龜壳里'),
('臺南市','安南區','𥂁田里','塩田里'),
('臺南市','七股區','𥂁埕里','塩埕里'),
('臺南市','新化區','𦰡拔里','[那]拔里'),
('臺南市','龍崎區','石𥕢里','石[曹]里'),
('新北市','坪林區','石𥕢里','石[曹]里'),
('新北市','瑞芳區','濓洞里','濂洞里'),
('新北市','瑞芳區','濓新里','濂新里'),
('雲林縣','水林鄉','𣐤埔村','欍埔村'),
('彰化縣','埤頭鄉','永豐村','永豊村'),
('澎湖縣','馬公市','啓明里','啟明里')]
def prepare(geo,rows,norm):
    names=Counter(tuple(norm(f['properties'].get(k)) for k in ('COUNTYNAME','TOWNNAME','VILLNAME')) for f in geo['features'])
    keys=[tuple(norm(r.get(k)) for k in ('縣市','鄉鎮市區','村里')) for r in rows]
    counts=Counter(keys);rules={tuple(norm(x) for x in r[:3]):r for r in RULES}
    proposed=[];audit=[]
    for i,key in enumerate(keys):
        rule=rules.get(key)
        if not rule:continue
        target=tuple(norm(x) for x in (rule[0],rule[1],rule[3]))
        item={'row':i+1,'county':rule[0],'town':rule[1],'source_village':rows[i]['村里'],'boundary_village':rule[3],'kind':'scoped_name_representation','status':'pending'}
        if names[key]:item['status']='kept_original_match'
        elif names[target]!=1:item['status']='target_not_unique_or_absent'
        elif counts[key]!=1 or counts[target]:item['status']='source_or_target_collision'
        else:proposed.append((i,target,item))
        audit.append(item)
    targets=Counter(target for i,target,item in proposed)
    adjusted=[dict(r) for r in rows]
    for i,target,item in proposed:
        if targets[target]!=1:item['status']='alias_collision';continue
        adjusted[i]['村里']=item['boundary_village'];item['status']='applied'
    return adjusted,audit
def main():
    import build_income_map as base
    import map_official_income as official
    original=base.join_income;state={}
    def join(geo,rows):
        adjusted,audit=prepare(geo,rows,base.norm)
        geo,q,issues=original(geo,adjusted)
        for issue in issues:
            if 'row' in issue:issue['village']=rows[issue['row']-1].get('村里')
        for item in audit:
            if item['status']=='applied':
                key=tuple(base.norm(item[k]) for k in ('county','town','boundary_village'))
                matches=[f for f in geo['features'] if tuple(base.norm(f['properties'].get(k)) for k in ('COUNTYNAME','TOWNNAME','VILLNAME'))==key]
                item['matched_income']=len(matches)==1 and matches[0]['properties'].get('income_median') is not None
        state['audit']=audit
        named=[f for f in geo['features'] if str(f['properties'].get('VILLNAME') or '').strip()]
        q['named_boundary_features']=len(named)
        q['unnamed_boundary_features']=len(geo['features'])-len(named)
        q['named_boundary_coverage']=sum(f['properties'].get('income_median') is not None for f in named)/len(named) if named else None
        state['extra']={k:q[k] for k in ('named_boundary_features','unnamed_boundary_features','named_boundary_coverage')}
        return geo,q,issues
    base.join_income=join
    try:
        with redirect_stdout(io.StringIO()):official.main()
    finally:base.join_income=original
    audit=state['audit'];applied=sum(i['status']=='applied' for i in audit)
    meta={'alias_rules_applied':bool(applied),'scoped_name_fixes_applied':applied,'original_income_csv_preserved':True,'administrative_boundary_changes_resolved':False,'private_use_characters_resolved':False,'alias_audit':audit,**state['extra']}
    for path in (Path('official-income-site/quality.json'),Path('reports/income/official-map-quality.json')):
        q=json.loads(path.read_text(encoding='utf-8'));q.update(meta);path.write_text(json.dumps(q,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    for path in (Path('official-income-site/name-fixes.json'),Path('reports/income/official-map-name-fixes.json')):path.write_text(json.dumps(audit,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'scoped_name_fixes_applied':applied,'site_deployed':False},ensure_ascii=False))
if __name__=='__main__':main()
