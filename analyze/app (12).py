#!/usr/bin/env python3
"""
OOTP ANALYZE -- web front end.  Upload an export, get the workbook back.

Served at https://ootptools.com/analyze/ by nginx -> 127.0.0.1:8506.
All URLs in the page are RELATIVE and the POST route is /run, so the app works
under any path prefix without knowing what it is.

Wraps ootp_analyze.py without duplicating a single constant: it imports the module
and calls the same load/build/score/write path the command line uses, so the web
page and the CLI can never drift apart.

    pip install flask openpyxl
    python3 app.py                      # http://localhost:8506
    PORT=9000 python3 app.py            # or pick a port

Every upload runs the 329-check self-test FIRST.  If a check fails the page says so
and writes nothing (methodology rule 22).
"""
import os
import uuid, sys, io, time, tempfile, traceback, threading
from flask import Flask, request, send_file, Response, render_template_string

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ootp_analyze as T

app = Flask(__name__)
# Behind nginx at /analyze/ -- trust the proxy headers it sets.
try:
    from werkzeug.middleware.proxy_fix import ProxyFix
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)
except Exception:
    pass
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024      # 16 MB -- see MAX_ROWS
# A real league export is ~1,600 rows and takes ~60s. Measured throughput is ~37 ms/row,
# so an uncapped upload could hold a worker for 40+ minutes and two of them would take
# the whole site down. Cap the WORK, not just the bytes.
MAX_ROWS = 5000
ALLOWED = {'.csv', '.tsv', '.txt', '.xlsx', '.xlsm'}
_verify_lock = threading.Lock()
_verified = {'ok': None, 'when': 0, 'output': ''}

def run_verify(max_age=3600):
    """Run the self-test, cached for an hour.  Returns (ok, captured_output)."""
    with _verify_lock:
        if _verified['ok'] is not None and time.time() - _verified['when'] < max_age:
            return _verified['ok'], _verified['output']
        buf = io.StringIO(); old = sys.stdout
        try:
            sys.stdout = buf
            fails = T.verify()
        finally:
            sys.stdout = old
        _verified.update(ok=(fails == 0), when=time.time(), output=buf.getvalue())
        return _verified['ok'], _verified['output']

PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>OOTP Analyze</title>
<base href="./"><style>
:root{--bg:#0f172a;--card:#1e293b;--line:#334155;--fg:#e2e8f0;--mut:#94a3b8;
      --ok:#34d399;--bad:#f87171;--acc:#60a5fa}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);
     font:15px/1.6 ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
     padding:24px 16px}
.wrap{max-width:660px;margin:0 auto}
h1{font-size:22px;margin:0 0 4px}
.sub{color:var(--mut);font-size:13px;margin-bottom:24px}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;
      padding:20px;margin-bottom:16px}
label.drop{display:block;border:2px dashed var(--line);border-radius:10px;padding:28px 16px;
      text-align:center;cursor:pointer;transition:.15s}
label.drop:hover{border-color:var(--acc);background:#243044}
label.drop input{display:none}
.fname{color:var(--acc);font-weight:600;margin-top:8px;word-break:break-all}
button{width:100%;margin-top:16px;padding:13px;border:0;border-radius:9px;
       background:var(--acc);color:#0b1220;font-size:15px;font-weight:700;cursor:pointer}
button:disabled{opacity:.5;cursor:default}
.status{margin-top:14px;font-size:13px;color:var(--mut);display:none}
.status.on{display:block}
.spin{display:inline-block;width:13px;height:13px;border:2px solid var(--line);
      border-top-color:var(--acc);border-radius:50%;animation:s .8s linear infinite;
      vertical-align:-2px;margin-right:7px}
@keyframes s{to{transform:rotate(360deg)}}
.pill{display:inline-block;padding:2px 9px;border-radius:99px;font-size:11px;font-weight:700}
.pill.ok{background:#064e3b;color:var(--ok)}.pill.bad{background:#7f1d1d;color:var(--bad)}
ul{margin:10px 0 0;padding-left:20px;color:var(--mut);font-size:13px}
li{margin:3px 0}
code{background:#0b1220;padding:1px 6px;border-radius:4px;font-size:12px}
.err{background:#7f1d1d;border-color:#b91c1c;color:#fecaca;white-space:pre-wrap;
     font-family:ui-monospace,monospace;font-size:12px}
a{color:var(--acc)}
select{width:100%;margin-top:6px;padding:9px;border-radius:8px;background:#0b1220;
       color:var(--fg);border:1px solid var(--line);font-size:14px}
.hint{color:var(--mut);font-size:12px;margin-top:6px}
</style></head><body><div class="wrap">
<h1>OOTP Analyze</h1>
<div class="sub">Registry v16 &middot; A1&ndash;A115 &middot; self-test
  <span class="pill {{'ok' if ok else 'bad'}}">{{ 'PASSING' if ok else 'FAILING' }}</span>
</div>

{% if not ok %}
<div class="card err">THE SELF-TEST SUITE IS FAILING. Nothing will be analysed.
Run <code>python3 ootp_analyze.py verify</code> on the box and send the output.

{{ vout }}</div>
{% else %}
<form class="card" id="f" method="post" action="run" enctype="multipart/form-data">
  <label class="drop" id="d">
    <input type="file" name="export" id="i" accept=".csv,.tsv,.txt,.xlsx,.xlsm" required>
    <div><strong>Choose an OOTP export</strong></div>
    <div style="color:var(--mut);font-size:13px;margin-top:4px">
      .csv or .xlsx &middot; draft pool or league file &middot; detected automatically</div>
    <div class="fname" id="n"></div>
  </label>
  <div style="margin-top:16px">
    <strong style="font-size:13px">Export kind</strong>
    <select name="kind" id="k">
      <option value="">Detect automatically</option>
      <option value="LEAGUE">Force LEAGUE &mdash; a single team's roster</option>
      <option value="POOL">Force POOL &mdash; a draft class</option>
    </select>
    <div class="hint">A <b>single-team roster</b> is neither a pool nor a league, so
      detection refuses it (G9). Force <b>LEAGUE</b> to analyse it anyway: you get every
      player-level sheet, and BASELINES / ACE CENSUS are withheld because one club cannot
      supply league context (G10). Force <b>POOL</b> only for an actual draft class &mdash;
      career-WAR projection is a draft-day model and is meaningless on established players.</div>
  </div>
  <button type="submit" id="b" disabled>Analyse</button>
  <div class="status" id="s"><span class="spin"></span><span id="st">Working…</span></div>
</form>

<div class="card">
  <strong style="font-size:13px">What comes back</strong>
  <ul>
    <li><b>BOARD</b> &mdash; bats and arms ranked together (draft pools)</li>
    <li><b>BATS</b> &mdash; landing spot on the tools, P10/P50/P90, P(POW&nbsp;55), position value</li>
    <li><b>ARMS</b> &mdash; stamina, <em>both</em> arsenal counts with A115 disagreements flagged</li>
    <li><b>GATED</b> &mdash; only those clearing the glove and role gates</li>
    <li><b>BASELINES / ACE CENSUS</b> &mdash; league files only, ORG-filtered</li>
    <li><b>KEY</b> &mdash; provenance, every gate with its source, the active guards</li>
  </ul>
  <ul style="margin-top:12px">
    <li>A league file of ~1,500 players takes about <b>30 seconds</b>. A draft pool takes a few.</li>
    <li>Position ratings are ignored for every gate, on purpose.</li>
  </ul>
</div>
{% endif %}
</div>
<script>
const i=document.getElementById('i'),n=document.getElementById('n'),
      b=document.getElementById('b'),f=document.getElementById('f'),
      s=document.getElementById('s'),st=document.getElementById('st'),d=document.getElementById('d');
if(i){
  i.onchange=()=>{ if(i.files[0]){ n.textContent=i.files[0].name; b.disabled=false; } };
  ['dragover','dragenter'].forEach(e=>d.addEventListener(e,ev=>{ev.preventDefault();
     d.style.borderColor='var(--acc)';}));
  ['dragleave','drop'].forEach(e=>d.addEventListener(e,ev=>{ev.preventDefault();
     d.style.borderColor='var(--line)';}));
  d.addEventListener('drop',ev=>{ if(ev.dataTransfer.files[0]){ i.files=ev.dataTransfer.files;
     i.dispatchEvent(new Event('change')); }});
  f.onsubmit=()=>{ b.disabled=true; s.classList.add('on');
     const big=i.files[0].size>400000;
     st.textContent = big ? 'Working — a league file takes about 90 seconds…'
                          : 'Working — running 329 self-tests, then the board…';
     setTimeout(()=>{ b.disabled=false; s.classList.remove('on'); }, 240000); };
}
</script></body></html>"""

@app.route('/')
def index():
    ok, vout = run_verify()
    return render_template_string(PAGE, ok=ok, vout=vout)

@app.route('/healthz')
def healthz():
    ok, _ = run_verify()
    return ({'ok': ok, 'version': T.VERSION}, 200 if ok else 503)

@app.route('/run', methods=['POST'])
def analyze():
    ok, vout = run_verify(max_age=0)          # never serve a stale pass
    if not ok:
        return Response("SELF-TEST FAILED -- nothing was analysed.\n\n" + vout,
                        mimetype='text/plain', status=500)
    kind = (request.form.get('kind') or '').strip().upper() or None
    if kind and kind not in ('POOL', 'LEAGUE'):
        return Response(f"Unknown export kind {kind!r}.", mimetype='text/plain', status=400)
    up = request.files.get('export')
    if not up or not up.filename:
        return Response("No file received.", mimetype='text/plain', status=400)
    ext = os.path.splitext(up.filename)[1].lower()
    if ext not in ALLOWED:
        return Response(f"Unsupported file type '{ext}'. Use .csv or .xlsx.",
                        mimetype='text/plain', status=400)
    req_id = uuid.uuid4().hex[:12]
    with tempfile.TemporaryDirectory() as td:
        src = os.path.join(td, 'export' + ext)
        up.save(src)
        try:
            rows = T.load(src)
            if len(rows) > MAX_ROWS:
                return Response(
                    f"That file has {len(rows):,} rows; this page accepts up to {MAX_ROWS:,}.\n"
                    "Filter the export first, or run the tool locally.",
                    mimetype='text/plain', status=413)
            fr = T.Frame(rows, src, kind=kind, orig_name=os.path.basename(up.filename))
            # FIX 2026-09-19: the web path skipped check_columns() entirely, so a file with
            # only a Name column returned 200 and an EMPTY workbook. It raises SystemExit on a
            # missing REQUIRED column (caught below -> 400) and returns the soft list.
            thin = T.check_columns(fr)
            players = T.build(fr)
            if not players:
                return Response(
                    "That file parsed but produced ZERO usable players.\n"
                    "Most often the Age or POS column is text rather than a number.\n"
                    "Nothing was written -- an empty workbook is worse than an error.",
                    mimetype='text/plain', status=400)
            notes = [f"detected {fr.kind} export (G9)." if not kind else
                     f"EXPORT KIND FORCED to {fr.kind} by the uploader; automatic "
                     f"detection (G9) was overridden."]
            if getattr(fr, 'single_org', False):
                notes.append("G10 -- this export contains ONE organisation. BASELINES and "
                             "the ACE CENSUS were NOT computed: league context cannot come "
                             "from a single club. Every player-level sheet is unaffected.")
            if thin:
                notes.append("LIMITED ANALYSIS -- these tool columns were absent, so anything "
                             "derived from them is missing or degraded: " + ", ".join(thin))
            if fr.kind == 'POOL':
                T.score(players)
            else:
                for p in players: p['ewar'] = p['ewar_adj'] = None
                notes.append('LEAGUE export: E[career WAR] is a DRAFT-DAY model (A104) and is '
                             'not computed for established players.')
            conf = [p['name'] for p in players if p.get('eff_conflict')]
            if conf:
                notes.append(f"A115 OPEN CONFLICT -- {len(conf)} arm(s) counted differently by "
                             f"A41 (changeup floor 45) and A103 (flat 40): {', '.join(conf[:15])}"
                             + (' ...' if len(conf) > 15 else ''))
            flips = [p['name'] for p in players if p.get('role_flips')]
            if flips:
                notes.append("*** A115 CHANGES THE ROLE VERDICT for "
                             f"{len(flips)} arm(s): {', '.join(flips)}. Under A41 they are "
                             "RELIEVERS; under A103 they are STARTERS. E[career WAR] uses A41.")
            out = os.path.join(td, 'ANALYSIS.xlsx')
            T.write_workbook(fr, players, out, notes)
            base = os.path.splitext(os.path.basename(up.filename))[0][:60]
            data = open(out, 'rb').read()
        except SystemExit as e:
            return Response(f"Could not read that file.\n\n{e}", mimetype='text/plain', status=400)
        except Exception:
            # Never hand the browser a traceback: it leaks server paths and source lines.
            app.logger.error("request %s failed\n%s", req_id, traceback.format_exc())
            return Response(f"Analysis failed.\n\nReference: {req_id}\n"
                            "Details are in the server log. Nothing was written.",
                            mimetype='text/plain', status=500)
    return send_file(io.BytesIO(data), as_attachment=True,
                     download_name=f"{base}_ANALYSIS.xlsx",
                     mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8506))
    print(f"ootp_analyze web  {T.VERSION}")
    print(f"  http://0.0.0.0:{port}   (nginx serves this at /analyze/)")
    app.run(host='0.0.0.0', port=port, threaded=True)
