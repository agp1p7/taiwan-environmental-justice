import functools,http.server,json,os,threading
from pathlib import Path
from playwright.sync_api import sync_playwright
ROOT=Path('integrated-preview')
class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self,*args):pass
def main():
    report={'status':'failed','checks':[],'environmental_api_requests':0,'base_map_tiles_network_verified':False,'site_deployed':False,'artifact_name':'environmental-integration-preview','actions_run_url':'https://github.com/'+os.environ.get('GITHUB_REPOSITORY','')+'/actions/runs/'+os.environ.get('GITHUB_RUN_ID','')}
    server=None;current='source_files'
    try:
        quality=json.loads((ROOT/'quality.json').read_text(encoding='utf-8'))
        expected_boundaries=quality['valid_named_boundary_features']+quality['unnamed_boundary_features_excluded']+quality['invalid_named_boundary_features_excluded']
        expected_soil=quality['datasets']['EMS_S_07']['counts']['unique_full_rows']
        handler=functools.partial(QuietHandler,directory=str(ROOT.resolve()))
        server=http.server.ThreadingHTTPServer(('127.0.0.1',0),handler);threading.Thread(target=server.serve_forever,daemon=True).start()
        url='http://127.0.0.1:'+str(server.server_port)+'/'
        with sync_playwright() as pw:
            browser=pw.chromium.launch()
            for label,width,height in [('desktop',1280,900),('mobile',390,844)]:
                page=browser.new_page(viewport={'width':width,'height':height});errors=[]
                page.on('pageerror',lambda error:errors.append(type(error).__name__))
                page.route('**/*.tile.openstreetmap.org/**',lambda route:route.abort())
                current=label+'_load';page.goto(url,wait_until='domcontentloaded',timeout=90000)
                page.wait_for_function('window.preview && window.preview.ready',timeout=180000)
                assert page.evaluate('window.preview.boundaries')==expected_boundaries
                assert page.evaluate('window.preview.soilPoints')==expected_soil
                report['checks'].append(current)
                current=label+'_metrics'
                for metric in ('ems01_records','soil_records','income_median'):
                    page.locator('#metric').select_option(metric)
                    page.wait_for_function('(metric)=>window.preview.metric===metric',arg=metric)
                report['checks'].append(current)
                current=label+'_soil_toggle'
                page.locator('#soil-toggle').check();page.wait_for_function('window.preview.soilVisible===true')
                page.locator('#soil-toggle').uncheck();page.wait_for_function('window.preview.soilVisible===false');report['checks'].append(current)
                current=label+'_zoom';old=page.evaluate('window.preview.map.getZoom()')
                page.locator('.leaflet-control-zoom-in').click();assert page.evaluate('window.preview.map.getZoom()')>old;report['checks'].append(current)
                current=label+'_popup'
                opened=page.evaluate("""()=>{let chosen;window.preview.map.eachLayer(l=>{if(!chosen&&l.feature&&l.feature.geometry.type!=='Point'&&l.getPopup&&l.getPopup())chosen=l});if(!chosen)return false;chosen.openPopup();return true}""")
                assert opened;page.locator('.leaflet-popup-content').wait_for(state='visible');page.evaluate('window.preview.map.closePopup()');report['checks'].append(current)
                current=label+'_layout'
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
                assert page.locator('#coverage').inner_text() and page.locator('#status').inner_text().startswith('已載入')
                assert not errors;report['checks'].append(current)
                page.screenshot(path=str(ROOT/(label+'-preview.png')),full_page=True);page.close()
            browser.close()
        report['status']='passed'
    except Exception as error:report['failed_check']=current;report['error_type']=type(error).__name__
    finally:
        if server:server.shutdown()
        output=Path('reports/environment/browser-acceptance.json');output.parent.mkdir(parents=True,exist_ok=True)
        text=json.dumps(report,ensure_ascii=False,indent=2);output.write_text(text,encoding='utf-8');(ROOT/'browser-acceptance.json').write_text(text,encoding='utf-8')
    if report['status']!='passed':raise SystemExit(1)
if __name__=='__main__':main()
