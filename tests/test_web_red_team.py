"""Installed-Chrome checks of the real renderer with synthetic responses only.

No app import, server, credentials, ledger, model, or external source request.
External page assets are removed; browser profiles live in temporary directories.
"""
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

import pytest

ROOT = Path(__file__).resolve().parents[1]
CHROME = Path('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome')


class ResultParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.collect = False
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag == 'pre' and dict(attrs).get('id') == 'browser-result':
            self.collect = True

    def handle_endtag(self, tag):
        if tag == 'pre':
            self.collect = False

    def handle_data(self, data):
        if self.collect:
            self.parts.append(data)


def render_in_chrome(*, html_error=False, bad_url=False, mobile=False, css_override=None, markdown=False):
    chrome = str(CHROME) if CHROME.exists() else shutil.which('chromium')
    if not chrome:
        pytest.skip('An installed Chrome/Chromium is required; never install for this test.')
    html = (ROOT / 'web/index.html').read_text()
    html = re.sub(r'<(?:link|img)\b[^>]*>', '', html)
    html = re.sub(r'<script\b[^>]*src=[^>]*>\s*</script>', '', html)
    css = (ROOT / 'web/styles.css').read_text() if css_override is None else css_override
    html = html.replace('</head>', '<style>' + css + '</style></head>')
    renderer = (ROOT / 'web/app.js').read_text()
    renderer, count = re.subn(
        r'import\s*\{[^}]*\}\s*from\s*[\"\']/static/voice\.js[\"\'];', '', renderer
    )
    assert count == 1, 'Review harness against changed voice imports before running.'
    fixture = {
        'mode': 'rehearsal', 'planner': 'scripted rehearsal; no Muse inference',
        'summary': '<img src=x onerror=alert(1)> Synthetic public-source answer.',
        'quotes_ok': True, 'complete': True,
        'source_cards': [{'title': '<b>Synthetic title</b>', 'url': 'https://example.invalid/source'}],
        'opened_sources': [
            {'id': 'local-source-1', 'title': '<b>Synthetic title</b>', 'tool': 'case_get',
             'text': '<img src=x onerror=alert(1)>\nPublic synthetic opinion body.',
             'truncated': True, 'characters_total': 123456},
            {'id': 'local-source-2', 'title': 'Second source', 'tool': 'ic_get_section',
             'text': 'Separate statutory body.', 'truncated': False, 'characters_total': 24},
        ],
        'steps': [],
    }
    if markdown:
        fixture['summary'] = '**Research note**\n\n[Read statute](https://example.invalid/statute) <img src=x onerror=alert(1)> [Bad](javascript:alert(1))'
    if mobile:
        fixture['steps'] = [{'tool': 'ic_get_companion', 'arguments': {'doc_id': 'public-synthetic-' + 'x' * 120}, 'result': {'text_ending': 'Public synthetic source ending.'}}]
        fixture['opened_sources'][0]['title'] = 'Public-source-' + 'x' * 200
        fixture['opened_sources'][0]['text'] += '\n' + 'long-unbroken-source-text-' * 200
    if bad_url:
        fixture['source_cards'].append({
            'title': 'Untrusted scheme',
            'url': 'javascript:void(document.body.dataset.syntheticExecuted="yes")',
        })
    setup = '''
let requests = [], finishes = 0, errors = [];
function newTurnSignal() { return new AbortController().signal; }
function turnFinished() { finishes++; }
window.addEventListener('unhandledrejection', e => {
  errors.push(String(e.reason)); e.preventDefault();
});
window.fetch = async (url, options) => {
  if (url === '/health') return new Response(JSON.stringify({spark_ready:false,spend:{note:'Synthetic closed'}}));
  if (url === '/warmup') return new Response('{}');
  if (url !== '/research') throw new Error('Unexpected URL: ' + url);
  requests.push(JSON.parse(options.body));
  if (HTML_ERROR) return new Response('<html>synthetic upstream failure</html>', {status:500});
  return new Response(JSON.stringify(FIXTURE), {status:200});
};
'''.replace('HTML_ERROR', json.dumps(html_error)).replace('FIXTURE', json.dumps(fixture))
    probe = '''
setTimeout(async () => {
  document.querySelector('.chips button').click();
  document.getElementById('form').dispatchEvent(new Event('submit', {cancelable:true}));
  await new Promise(resolve => setTimeout(resolve, 150));
  const links = [...document.querySelectorAll('#cards a')];
  for (const link of links) if (link.protocol === 'javascript:') link.click();
  const sourceButtons = [...document.querySelectorAll('[data-source-id]')];
  if (sourceButtons[0]) sourceButtons[0].click();
  if (MOBILE && document.getElementById('trace-details')) document.getElementById('trace-details').open = true;
  await new Promise(resolve => setTimeout(resolve, 20));
  const result = {
    requests, finishes, errors,
    viewport: window.innerWidth, documentWidth: document.documentElement.scrollWidth,
    status: document.getElementById('status').textContent,
    answerHidden: document.getElementById('out').hidden,
    summary: document.getElementById('summary').textContent,
    summaryChildren: document.getElementById('summary').children.length,
    summaryImages: document.querySelectorAll('#summary img').length,
    summaryLinks: [...document.querySelectorAll('#summary a')].map(a=>a.href),
    summaryStrong: document.querySelector('#summary strong')?.textContent,
    title: document.querySelector('#cards strong')?.textContent,
    urls: links.map(link => link.href),
    executed: document.body.dataset.syntheticExecuted || null,
    sourceButtons: sourceButtons.length,
    sourceText: document.getElementById('source-text')?.textContent,
    sourceChildren: document.getElementById('source-text')?.children.length,
    sourceTitle: document.getElementById('source-title')?.textContent,
    sourceNotice: document.getElementById('source-notice')?.textContent,
    traceClosed: document.getElementById('trace-details')?.open === false,
  };
  if (sourceButtons[1]) {
    sourceButtons[1].click();
    result.secondSourceText = document.getElementById('source-text')?.textContent;
    document.getElementById('close-source').click();
    result.readerClosed = document.getElementById('source-reader').hidden;
    result.focusReturned = document.activeElement === sourceButtons[1];
  }
  const pre = document.createElement('pre');
  pre.id = 'browser-result'; pre.textContent = JSON.stringify(result);
  document.body.append(pre);
}, 30);
'''.replace('MOBILE', json.dumps(mobile))
    script = setup + renderer + probe
    assert '</script' not in script.lower()
    html = html.replace('</body>', '<script>' + script + '</script></body>')
    with tempfile.TemporaryDirectory(prefix='muse-web-red-team-') as directory:
        temp = Path(directory)
        page = temp / 'test.html'
        page.write_text(html)
        if mobile:
            node = shutil.which('node')
            if not node:
                pytest.skip('Mobile emulation needs installed Node with native WebSocket.')
            cdp_script = r"""
const fs=require('fs'),path=require('path'),cp=require('child_process');
(async()=>{
 const [chrome, directory, url] = process.argv.slice(1);
 const profile=path.join(directory,'profile');
 const child=cp.spawn(chrome,['--headless','--disable-gpu','--disable-background-networking',
   '--no-first-run','--remote-debugging-port=0','--host-resolver-rules=MAP * ~NOTFOUND',
   '--user-data-dir='+profile,'about:blank'],{stdio:'ignore'});
 let socket;
 try {
  const portfile=path.join(profile,'DevToolsActivePort');
  for(let i=0;i<100&&!fs.existsSync(portfile);i++)await new Promise(r=>setTimeout(r,50));
  const port=fs.readFileSync(portfile,'utf8').split('\n')[0];
  const pages=await (await fetch('http://127.0.0.1:'+port+'/json')).json();
  socket=new WebSocket(pages.find(p=>p.type==='page').webSocketDebuggerUrl);
  await new Promise((resolve,reject)=>{socket.onopen=resolve;socket.onerror=reject;});
  let serial=0,pending=new Map();
  socket.onmessage=e=>{const o=JSON.parse(e.data);if(o.id){const p=pending.get(o.id);
   pending.delete(o.id);o.error?p.reject(o.error):p.resolve(o.result);}};
  const call=(method,params={})=>new Promise((resolve,reject)=>{const id=++serial;
   pending.set(id,{resolve,reject});socket.send(JSON.stringify({id,method,params}));});
  const evaluate=async expression=>(await call('Runtime.evaluate',{
   expression,awaitPromise:true,returnByValue:true})).result.value;
  await call('Emulation.setDeviceMetricsOverride',{
   width:390,height:844,deviceScaleFactor:1,mobile:true});
  await call('Page.navigate',{url});
  for(let i=0;i<100;i++){
   if(await evaluate("Boolean(document.getElementById('browser-result'))"))break;
   await new Promise(r=>setTimeout(r,50));
  }
  console.log(await evaluate('document.documentElement.outerHTML'));
 } finally {if(socket)socket.close();child.kill();}
})().catch(error=>{console.error(error);process.exitCode=1;});
"""
            run = subprocess.run(
                [node, '-e', cdp_script, chrome, str(temp), page.as_uri() + '?record=1&demo=eviction'],
                text=True, capture_output=True, timeout=20,
            )
        else:
            run = subprocess.run([
                chrome, '--headless', '--disable-gpu', '--disable-background-networking',
                '--no-first-run', '--no-default-browser-check', '--disable-sync',
                '--host-resolver-rules=MAP * ~NOTFOUND',
                '--user-data-dir=' + str(temp / 'profile'), '--dump-dom',
                '--virtual-time-budget=2000', page.as_uri(),
            ], text=True, capture_output=True, timeout=20)
        assert run.returncode == 0, run.stderr[-2000:]
        parsed = ResultParser()
        parsed.feed(run.stdout)
        assert parsed.parts, 'Browser did not finish synthetic UI probe.'
        return json.loads(''.join(parsed.parts))


def test_rehearsal_mode_label_and_text_are_preserved_in_browser():
    result = render_in_chrome()
    assert result['requests'][0]['mode'] == 'rehearsal'
    assert 'REHEARSAL' in result['status'] and 'no live Muse' in result['status']
    assert not result['answerHidden']
    assert result['summary'].startswith('<img src=x')
    assert result['summaryImages'] == 0
    assert result['title'] == '<b>Synthetic title</b>'
    assert result['urls'] == ['https://example.invalid/source']
    assert result['finishes'] >= 1 and result['errors'] == []


def test_source_links_reject_script_urls_in_browser():
    result = render_in_chrome(bad_url=True)
    assert result['executed'] is None, 'Untrusted source URL executed JavaScript.'
    assert all(url.startswith(('https://', 'http://')) for url in result['urls'])
    assert 'https://example.invalid/source' in result['urls']


def test_html_server_error_recovers_browser_status():
    result = render_in_chrome(html_error=True)
    assert result['errors'] == [], 'Non-JSON server response escaped renderer error handling.'
    assert result['finishes'] >= 1
    assert result['status'] != 'Finding unofficial sources…'
    assert result['answerHidden']


def test_mobile_rehearsal_trace_does_not_expand_the_viewport():
    result = render_in_chrome(mobile=True)
    assert result['viewport'] == 390
    assert result['documentWidth'] <= result['viewport']
    assert 'REHEARSAL' in result['status'] and not result['answerHidden']
    assert result['sourceButtons'] == 2 and result['sourceChildren'] == 0


def test_opened_source_reader_is_plain_text_and_selects_by_local_id():
    result = render_in_chrome()
    assert result['sourceButtons'] == 2
    assert result['sourceText'] == '<img src=x onerror=alert(1)>\nPublic synthetic opinion body.'
    assert result['sourceChildren'] == 0
    assert result['sourceTitle'] == '<b>Synthetic title</b>'
    assert 'truncated' in result['sourceNotice'].lower()
    assert '123,456' in result['sourceNotice']
    assert result['secondSourceText'] == 'Separate statutory body.'
    assert result['traceClosed']
    assert result['readerClosed'] and result['focusReturned']
    assert len(result['requests']) == 1, 'Reading already retrieved text must not start another research request.'
    assert result['executed'] is None and result['errors'] == []


def test_research_note_formats_links_and_emphasis_without_interpreting_html():
    result=render_in_chrome(markdown=True)
    assert result['summaryLinks']==['https://example.invalid/statute']
    assert result['summaryStrong']=='Research note'
    assert result['summaryImages']==0 and result['executed'] is None
