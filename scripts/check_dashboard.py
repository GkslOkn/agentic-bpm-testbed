"""Optional live browser check using the already installed Windows Edge."""
import json
import subprocess
import uuid
from pathlib import Path
from testbed.models import ROOT


def main():
    paths=list((ROOT/'artifacts/runs').glob('*/metadata.json'))
    runs=[json.loads(p.read_text()) for p in paths]
    selected=next(r for r in sorted(runs,key=lambda r:r['started_at'],reverse=True)
                  if r['status']=='finished' and r['config']['instances']==200 and r['metrics']['completed']==200)
    folder=ROOT/'artifacts/browser-check'/uuid.uuid4().hex
    folder.mkdir(parents=True)
    browser=Path('C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe')
    startup=subprocess.STARTUPINFO(); startup.dwFlags|=subprocess.STARTF_USESHOWWINDOW; startup.wShowWindow=0
    result=subprocess.run([str(browser),'--headless','--disable-gpu','--no-first-run',
        '--disable-extensions',f'--user-data-dir={folder / "profile"}',
        '--dump-dom','--virtual-time-budget=8000',f'http://127.0.0.1:8000/?run={selected["run_id"]}&page=6'],
        capture_output=True,timeout=45,startupinfo=startup)
    html=result.stdout.decode('utf-8',errors='replace')
    (folder/'dashboard.html').write_text(html,encoding='utf-8')
    (folder/'browser-stderr.txt').write_bytes(result.stderr)
    assert result.returncode==0,result.stderr.decode('utf-8',errors='replace')[-1000:]
    assert selected['run_id'] in html
    assert 'Process instance completed' in html
    assert '200' in html and 'No active native user tasks.' in html
    diagram=subprocess.run([str(browser),'--headless','--disable-gpu','--no-first-run',
        '--disable-extensions',f'--user-data-dir={folder / "profile"}',
        '--dump-dom','--virtual-time-budget=8000','http://127.0.0.1:8000/?page=1'],
        capture_output=True,timeout=45,startupinfo=startup)
    diagram_html=diagram.stdout.decode('utf-8',errors='replace')
    (folder/'diagram.html').write_text(diagram_html,encoding='utf-8')
    assert diagram.returncode==0
    assert 'data-element-id="validate"' in diagram_html and 'data-element-id="variant_route"' in diagram_html
    print(json.dumps({'browser':'installed Edge headless','run_id':selected['run_id'],
                      'rendered_real_events':True,'bpmn_js_rendered_executable_model':True,'artifact':str(folder/'dashboard.html')},indent=2))


if __name__=='__main__': main()
