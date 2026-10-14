#!/usr/bin/env python3
"""
Uso (dentro de la carpeta fba-demo, junto a docker-compose.yml, topology.json y fba_docker_demo.py):
    python fba_dashboard.py            # abre http://localhost:8080
    python fba_dashboard.py --port 9000
"""
import argparse
import json
import os
import re
import subprocess
import sys
import threading
import urllib.request
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
TOPO = os.path.join(HERE, "topology.json")
GEN = os.path.join(HERE, "fba_docker_demo.py")
MAX_NODES = 9
JOB = {"busy": False, "msg": ""}


def load_topology():
    try:
        with open(TOPO, encoding="utf-8") as f:
            t = json.load(f)
        nodes = t["nodes"]
        slices = {x: {"validators": t["slices"][x]["validators"], "threshold": int(t["slices"][x]["threshold"])}
                  for x in nodes}
        return {"nodes": nodes, "slices": slices}
    except Exception:
        nodes = [f"node{i}" for i in range(1, 5)]
        return {"nodes": nodes, "slices": {x: {"validators": nodes, "threshold": 3} for x in nodes}}


def fetch(n, path, timeout=1.5):
    try:
        with urllib.request.urlopen(f"http://localhost:{11625 + n}/{path}", timeout=timeout) as r:
            return json.load(r)
    except Exception:
        return None


def node_status(n):
    info = fetch(n, "info")
    if info is None:
        return {"n": n, "up": False}
    return {"n": n, "up": True, "info": info.get("info", info), "quorum": fetch(n, "quorum?transitive=true")}


def run(cmd, timeout=300):
    r = subprocess.run(cmd, cwd=HERE, capture_output=True, text=True, timeout=timeout)
    if r.returncode:
        raise RuntimeError((r.stderr or r.stdout)[-300:])


def apply_job():
    JOB.update(busy=True, msg="Parando la red…")
    try:
        if not os.path.exists(GEN):
            raise RuntimeError("falta fba_docker_demo.py en esta carpeta")
        run(["docker", "compose", "down", "-v", "--remove-orphans"])
        JOB["msg"] = "Generando la configuración (y claves de los nodos nuevos)…"
        run([sys.executable, GEN, "--out", HERE])
        JOB["msg"] = "Arrancando los nodos…"
        run(["docker", "compose", "up", "-d"])
        JOB["msg"] = "Red reiniciada con la nueva topología."
    except Exception as e:
        JOB["msg"] = "Error: " + str(e)
    finally:
        JOB["busy"] = False


def valid_topology(t):
    nodes = t["nodes"]
    assert 1 <= len(nodes) <= MAX_NODES and len(set(nodes)) == len(nodes)
    assert all(re.fullmatch(r"node\d+", x) for x in nodes)
    for x in nodes:
        s = t["slices"][x]
        assert set(s["validators"]) <= set(nodes) and 1 <= int(s["threshold"]) <= len(set(s["validators"]) | {x})
    return {"nodes": nodes, "slices": {x: {"validators": t["slices"][x]["validators"],
                                           "threshold": int(t["slices"][x]["threshold"])} for x in nodes}}


HTML = r'''<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Panel FBA · stellar-core</title>
<style>
:root{--bg:#0f1322;--card:#171c32;--line:#363e5e;--fg:#e8ebf7;--mut:#98a1bd;--ok:#4cd68a;--warn:#f3b43f;--bad:#ff7d8d;--acc:#8c9bff}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,"Segoe UI",sans-serif}
main{max-width:1180px;margin:0 auto;padding:16px}
h1{font:600 22px Georgia,serif;margin:0 0 4px}
.mut{color:var(--mut);font-size:13px}
#banner{padding:12px 16px;border-radius:12px;font-weight:600;margin:12px 0}
.ok{background:#12301f;color:var(--ok)}.warn{background:#3a2c0d;color:var(--warn)}.bad{background:#3a1520;color:var(--bad)}
.grid{display:grid;grid-template-columns:1.1fr 1fr;gap:14px}
@media(max-width:860px){.grid{grid-template-columns:1fr}}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px 14px;margin-bottom:14px}
svg{width:100%;height:auto;display:block}
button{font:inherit;color:var(--fg);background:var(--bg);border:1px solid var(--line);border-radius:8px;padding:5px 11px;cursor:pointer;margin:2px}
button:hover:not(:disabled){border-color:var(--acc)}button:disabled{opacity:.45;cursor:default}
button.go{background:var(--acc);color:#0f1322;border-color:var(--acc);font-weight:600}
input[type=number]{width:60px;background:var(--bg);color:var(--fg);border:1px solid var(--line);border-radius:6px;padding:3px 6px}
label.chk{display:inline-block;margin:2px 10px 2px 0;font-size:13px}
table{width:100%;border-collapse:collapse;font-size:13px}
td,th{padding:4px 6px;text-align:left;border-bottom:1px solid var(--line)}
#tl{display:flex;gap:4px;flex-wrap:wrap;margin-top:6px}
.blk{background:#12301f;color:var(--ok);border-radius:6px;padding:2px 8px;font-size:12px}
ul{margin:6px 0 0;padding-left:18px;font-size:13px}
pre{font-size:11px;max-height:220px;overflow:auto;background:var(--bg);padding:8px;border-radius:8px}
.tag{font-size:12px;background:#3a2c0d;color:var(--warn);border-radius:6px;padding:1px 8px;margin-left:6px}
</style></head><body><main>
<h1>Red privada de stellar-core · SCP / FBA</h1>
<div class="mut">Datos reales de los validadores, consultados cada segundo. Cada nodo decide en quién confía (sus quorum slices).</div>
<div id="banner" class="warn">Conectando con los nodos…</div>
<div class="grid"><div>
  <div class="card"><svg id="g" viewBox="0 0 400 300"><g id="edges"></g><g id="dots"></g><g id="nodes"></g></svg>
  <div class="mut">Pulsa un nodo para ver y editar su slice (flechas = en quién confía). Los puntos violeta se animan al cerrarse un ledger: ilustran una ronda de mensajes SCP.</div></div>
  <div class="card"><b>Control de nodos</b> <span class="mut">(simula fallos)</span><div id="ctl"></div></div>
  <div class="card"><b>Eventos</b><ul id="ev"></ul></div>
</div><div>
  <div class="card"><div id="stat"></div><div id="tl"></div></div>
  <div class="card" id="ed"></div>
  <div class="card"><table><thead><tr><th>Nodo</th><th>Estado</th><th>Ledger</th><th>Hash</th><th>Pares</th><th>Quórum (según el nodo)</th></tr></thead><tbody id="tb"></tbody></table></div>
  <div class="card"><details><summary>Datos crudos del primer nodo activo</summary><pre id="raw"></pre></details></div>
</div></div></main>
<script>
let topo=null, draft=null, sel=null, job={}, prev={}, maxL=0, lastClose=Date.now(), blocks=[], events=[], busy={}, raw={}, last=null, hist={}, fork=null;
const $=s=>document.querySelector(s), clone=o=>JSON.parse(JSON.stringify(o));
const setHTML=(el,h)=>{if(el.dataset.h!==h){el.dataset.h=h;el.innerHTML=h}};
const ev=t=>{events.unshift(new Date().toLocaleTimeString()+"  "+t);events=events.slice(0,12)};
const has=(T,x,S)=>{const s=T.slices[x];return new Set(s.validators.concat(x)).size&&[...new Set(s.validators.concat(x))].filter(v=>S.has(v)).length>=s.threshold};
const maxQ=(T,S)=>{S=new Set(S);let c=true;while(c){c=false;for(const x of [...S])if(!has(T,x,S)){S.delete(x);c=true}}return S};
function analyze(T){
  const n=T.nodes.length;if(n>10)return null;
  const qs=[];for(let m=1;m<(1<<n);m++){const S=new Set(T.nodes.filter((_,i)=>m>>i&1));if([...S].every(x=>has(T,x,S)))qs.push(S)}
  const mins=qs.filter(a=>!qs.some(b=>b!==a&&b.size<a.size&&[...b].every(x=>a.has(x))));
  let mi=Infinity;for(const a of mins)for(const b of mins)if(a!==b)mi=Math.min(mi,[...a].filter(x=>b.has(x)).length);
  if(!mins.length)mi=0;else if(mi===Infinity)mi=Math.min(...mins.map(q=>q.size));
  let live=-1;
  for(let f=0;f<=n;f++){let ok=true;
    for(let m=0;m<(1<<n)&&ok;m++){let c=0;for(let i=0;i<n;i++)if(m>>i&1)c++;if(c!==f)continue;
      if(!maxQ(T,T.nodes.filter((_,i)=>!(m>>i&1))).size)ok=false}
    if(ok)live=f;else break}
  return {mins,safe:mi-1,live};
}
const pos=(i,n)=>{const a=-Math.PI/2+2*Math.PI*i/n,R=n>6?115:105;return[200+R*Math.cos(a),150+R*Math.sin(a)]};
async function poll(){
  try{last=await (await fetch("/api/status")).json()}catch(e){return}
  topo=last.topology;job=last.job;
  if(!draft||JSON.stringify(draft)===JSON.stringify(topoSnap)){draft=clone(topo)}
  topoSnap=clone(topo);
  if(!sel||!draft.nodes.includes(sel))sel=draft.nodes[0];
  let led=0;
  last.nodes.forEach(d=>{const k=topo.nodes[d.n-1],L=d.up?(d.info?.ledger?.num??0):0,st=d.up?(d.info?.state||"?"):"caído";
    if(d.up){led=Math.max(led,L);raw[k]={info:d.info,quorum:d.quorum};const h=d.info?.ledger?.hash;if(h)(hist[L]=hist[L]||{})[k]=h}
    if(prev[k]&&prev[k].st!==st)ev(`${k}: ${prev[k].st} → ${st}`);prev[k]={st}});
  if(led<maxL){maxL=0;hist={};fork=null}
  detectFork();
  if(led>maxL){if(maxL){blocks.push(led);blocks=blocks.slice(-24);ev(`Ledger ${led} cerrado`);wave()}lastClose=Date.now();maxL=led}
  render();
}
let topoSnap=null;
function detectFork(){
  const Ls=Object.keys(hist).map(Number).sort((a,b)=>a-b).slice(-40);
  Object.keys(hist).forEach(k=>{if(!Ls.includes(+k))delete hist[k]});
  let at=null,latest=null;
  for(const L of Ls)if(new Set(Object.values(hist[L])).size>1){if(at===null)at=L;latest=L}
  if(at===null)return;
  const groups={};Object.entries(hist[latest]).forEach(([n,h])=>(groups[h]=groups[h]||[]).push(n));
  if(!fork)ev(`¡FORK detectado en el ledger ${at}!`);
  fork={at,latest,groups};
}
const hcol=h=>`hsl(${parseInt(h.slice(0,6),16)%360} 55% 45%)`;
function wave(){
  const T=topo,up=last.nodes.filter(d=>d.up).map(d=>d.n-1);
  up.forEach(a=>up.forEach(b=>{if(a===b)return;
    const[x1,y1]=pos(a,T.nodes.length),[x2,y2]=pos(b,T.nodes.length),c=document.createElementNS("http://www.w3.org/2000/svg","circle");
    c.setAttribute("r",4);c.setAttribute("cx",x1);c.setAttribute("cy",y1);c.setAttribute("fill","#8c9bff");$("#dots").appendChild(c);
    c.animate([{transform:"translate(0px,0px)",opacity:1},{transform:`translate(${x2-x1}px,${y2-y1}px)`,opacity:.2}],{duration:800,easing:"ease-in-out"}).onfinish=()=>c.remove()}));
}
function render(){
  const N=topo.nodes.length,since=(Date.now()-lastClose)/1000,b=$("#banner");
  const upNames=last.nodes.filter(d=>d.up).map(d=>topo.nodes[d.n-1]),mq=maxQ(topo,upNames),ups=upNames.length;
  if(job.busy){b.className="warn";b.textContent=job.msg}
  else if(job.msg&&job.msg.startsWith("Error")){b.className="bad";b.textContent=job.msg+" (la topología nueva ya está guardada en topology.json; puedes volver a pulsar «Aplicar»)"}
  else if(fork){b.className="bad";b.textContent=`FORK en el ledger ${fork.at}: `+Object.entries(fork.groups).map(([h,ns])=>`{${ns.join(", ")}} cierran el hash ${h.slice(0,6)}`).join(" · ")+". Cada grupo cree tener la cadena válida: no hay intersección de quórums."}
  else if(!ups){b.className="bad";b.textContent=job.msg&&job.msg.startsWith("Error")?job.msg:"Ningún nodo responde. ¿Está la red levantada (docker compose up -d)?"}
  else if(!mq.size){b.className="bad";b.textContent=`Sin quórum: los nodos activos (${upNames.join(", ")}) no contienen ningún quórum según los slices configurados. La red no cierra ledgers (se pierde la liveness), pero no se corrompe: no hay fork.`}
  else if(since>15){b.className="warn";b.textContent=`Esperando cierre de ledger (hace ${since.toFixed(0)} s)… la red se está recuperando.`}
  else if(ups<N){b.className="warn";b.textContent=`Red degradada: ${ups} de ${N} nodos activos. Siguen formando quórum: ${[...mq].join(", ")}.`}
  else{b.className="ok";b.textContent=`Red completa: ${N} de ${N} nodos activos y cerrando ledgers.`}
  const D=draft,n=D.nodes.length,st=name=>{const i=topo.nodes.indexOf(name);return i<0?null:last.nodes[i]};
  let e="";for(let i=0;i<n;i++)for(let j=i+1;j<n;j++){const[x1,y1]=pos(i,n),[x2,y2]=pos(j,n),a=st(D.nodes[i]),c=st(D.nodes[j]),ok=a&&c&&a.up&&c.up;
    e+=`<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" stroke="#363e5e" stroke-width="${ok?2:1}" ${ok?"":'stroke-dasharray="3 4"'}/>`}
  const si=D.nodes.indexOf(sel);
  if(si>=0)D.slices[sel].validators.forEach(v=>{if(v===sel)return;const j=D.nodes.indexOf(v);if(j<0)return;
    const[x1,y1]=pos(si,n),[x2,y2]=pos(j,n),L=Math.hypot(x2-x1,y2-y1),u=(x2-x1)/L,w=(y2-y1)/L;
    e+=`<line x1="${x1+u*34}" y1="${y1+w*34}" x2="${x2-u*38}" y2="${y2-w*38}" stroke="#8c9bff" stroke-width="2.5" marker-end="url(#ar)"/>`});
  setHTML($("#edges"),`<defs><marker id="ar" viewBox="0 0 8 8" refX="6" refY="4" markerWidth="6" markerHeight="6" orient="auto"><path d="M0 0L8 4L0 8z" fill="#8c9bff"/></marker></defs>`+e);
  const r=n>6?26:32;
  setHTML($("#nodes"),D.nodes.map((name,i)=>{const[x,y]=pos(i,n),d=st(name);let col="#98a1bd",sub="nuevo (sin aplicar)",dash=' stroke-dasharray="5 4"';
    if(d){dash="";if(!d.up){col="#ff7d8d";sub="caído"}else{const sync=/synced/i.test(d.info?.state||"");col=sync&&mq.has(name)?"#4cd68a":"#f3b43f";sub="ledger "+(d.info?.ledger?.num??"?")}}
    return `<g data-n="${name}" style="cursor:pointer"><circle cx="${x}" cy="${y}" r="${r}" fill="${d&&d.up&&d.info?.ledger?.hash?`hsl(${parseInt(d.info.ledger.hash.slice(0,6),16)%360} 45% 22%)`:"#171c32"}" stroke="${col}" stroke-width="${name===sel?7:4}"${dash}/><text x="${x}" y="${y-2}" text-anchor="middle" fill="#e8ebf7" font-size="${n>6?12:15}" font-weight="600">${name}</text><text x="${x}" y="${y+13}" text-anchor="middle" fill="${col}" font-size="${n>6?8:10}">${sub}</text></g>`}).join(""));
  document.querySelectorAll("#nodes g").forEach(g=>g.onclick=()=>{sel=g.dataset.n;render()});
  const inter=last.nodes.find(d=>d.up&&d.quorum?.transitive)?.quorum.transitive.intersection;
  setHTML($("#stat"),`<b>Ledger ${maxL||"—"}</b> · último cierre hace ${since.toFixed(0)} s · intersección según stellar-core: ${inter===true?'<span style="color:var(--ok)">se cumple ✓</span>':inter===false?'<span style="color:var(--bad)">NO se cumple ✗</span>':"—"}`);
  setHTML($("#tl"),blocks.map(x=>`<span class="blk">${x}</span>`).join(""));
  setHTML($("#tb"),last.nodes.map(d=>{const nm=topo.nodes[d.n-1];
    if(!d.up)return `<tr><td>${nm}</td><td style="color:var(--bad)">caído</td><td>—</td><td>—</td><td>—</td><td>—</td></tr>`;
    const q=d.quorum?.qset||{},miss=Array.isArray(q.missing)?q.missing.length:q.missing;
    return `<tr><td>${nm}</td><td>${d.info?.state??"?"}</td><td>${d.info?.ledger?.num??"—"}</td><td>${d.info?.ledger?.hash?`<span style="color:${hcol(d.info.ledger.hash)}">● ${d.info.ledger.hash.slice(0,6)}</span>`:"—"}</td><td>${d.info?.peers?.authenticated_count??"—"}</td><td>${q.agree!==undefined?`${q.agree} acuerdan · ${miss??0} faltan`:"—"}</td></tr>`}).join(""));
  setHTML($("#ev"),events.map(x=>`<li>${x}</li>`).join(""));
  setHTML($("#ctl"),last.nodes.map(d=>{const nm=topo.nodes[d.n-1];return `<button ${busy[d.n]||job.busy?"disabled":""} onclick="act(${d.n},'${d.up?"stop":"start"}')">${d.up?"⏹ Parar":"▶ Arrancar"} ${nm}</button>`}).join(""));
  const k=Object.keys(raw)[0];if(k)$("#raw").textContent=JSON.stringify(raw[k],null,1).slice(0,4000);
  renderEditor();
}
function renderEditor(){
  const D=draft,dirty=JSON.stringify(D)!==JSON.stringify(topo),a=analyze(D),s=D.slices[sel];
  if(document.activeElement&&document.activeElement.closest("#ed")&&document.activeElement.type==="number")return;
  const size=new Set(s.validators.concat(sel)).size;
  let h=`<b>Quorum slice de ${sel}</b>${dirty?'<span class="tag">cambios sin aplicar</span>':""}<div class="mut">Basta con que <input type="number" min="1" max="${size}" value="${s.threshold}" onchange="setT(this.value)"> de estos ${size} nodos (él mismo cuenta) le convenzan:</div><div>`;
  h+=D.nodes.map(x=>`<label class="chk"><input type="checkbox" ${s.validators.includes(x)||x===sel?"checked":""} ${x===sel?"disabled":""} onchange="setM('${x}',this.checked)"> ${x}</label>`).join("")+"</div>";
  h+=`<div style="margin-top:8px"><button onclick="addNode()" ${D.nodes.length>=9?"disabled":""}>+ Añadir nodo</button><button onclick="delNode()" ${D.nodes.length<=1?"disabled":""}>− Quitar último</button><button onclick="draft=clone(topo);render()" ${dirty?"":"disabled"}>Descartar</button><button class="go" onclick="apply()" ${dirty&&!job.busy?"":"disabled"}>Aplicar y reiniciar red</button></div>`;
  h+=`<div style="margin-top:6px"><span class="mut">Escenarios:</span> <button onclick="preset('sana')">Red sana (4 nodos, 3 de 4)</button><button onclick="preset('fork')">Fork: 2 grupos aislados (6 nodos)</button></div>`;
  h+=`<div style="margin-top:10px;font-size:13px"><b>Análisis de la configuración${dirty?" (borrador)":""}</b><br>`;
  if(!a)h+="Demasiados nodos para analizar.";
  else{h+=`Quórums mínimos (${a.mins.length}): ${a.mins.slice(0,6).map(q=>"{"+[...q].join(", ")+"}").join(" ")}${a.mins.length>6?" …":""}<br>`;
    h+=a.mins.length?`Safety: ${a.safe<0?'<span style="color:var(--bad)">sin intersección: puede haber fork</span>':`la intersección aguanta hasta <b>${a.safe}</b> nodo(s) bizantino(s)`}<br>Liveness: ${a.live<0?'<span style="color:var(--bad)">no hay quórum ni con todos los nodos</span>':`sigue habiendo quórum aunque caigan hasta <b>${a.live}</b> nodo(s) cualesquiera`}`:'<span style="color:var(--bad)">No existe ningún quórum: la red no puede cerrar ledgers.</span>'}
  setHTML($("#ed"),h+"</div>");
}
function preset(k){let nodes,sl={};
  if(k==="sana"){nodes=[1,2,3,4].map(i=>"node"+i);nodes.forEach(x=>sl[x]={validators:[...nodes],threshold:3})}
  else{nodes=[1,2,3,4,5,6].map(i=>"node"+i);const A=nodes.slice(0,3),B=nodes.slice(3);
    A.forEach(x=>sl[x]={validators:[...A],threshold:2});B.forEach(x=>sl[x]={validators:[...B],threshold:2})}
  draft={nodes,slices:sl};sel=nodes[0];render()}
function norm(T){T.nodes.forEach(x=>{const s=T.slices[x];s.validators=[...new Set(s.validators.filter(v=>T.nodes.includes(v)).concat(x))];s.threshold=Math.max(1,Math.min(s.threshold,s.validators.length))})}
function setT(v){draft.slices[sel].threshold=+v;norm(draft);render()}
function setM(x,on){const s=draft.slices[sel];s.validators=on?[...s.validators,x]:s.validators.filter(v=>v!==x);norm(draft);render()}
function addNode(){const n=draft.nodes.length,name="node"+(n+1);draft.nodes.push(name);
  draft.slices[name]={validators:[...draft.nodes],threshold:Math.floor(2*(n+1)/3)+1};norm(draft);sel=name;render()}
function delNode(){const name=draft.nodes.pop();delete draft.slices[name];norm(draft);if(sel===name)sel=draft.nodes[0];render()}
async function apply(){if(!confirm("Se reiniciará la red desde cero (el número de ledger vuelve a empezar). ¿Continuar?"))return;
  ev("Aplicando nueva topología…");await fetch("/api/apply",{method:"POST",body:JSON.stringify(draft)});blocks=[];maxL=0;hist={};fork=null}
async function act(n,a){busy[n]=true;ev(`${a==="stop"?"Parando":"Arrancando"} ${topo.nodes[n-1]}…`);
  try{await fetch(`/api/node/${n}/${a}`,{method:"POST"})}catch(e){}busy[n]=false}
poll();setInterval(poll,1000);
</script></body></html>'''


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def send(self, code, body, ctype="application/json"):
        data = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/":
            self.send(200, HTML, "text/html")
        elif self.path == "/api/status":
            topo = load_topology()
            with ThreadPoolExecutor(len(topo["nodes"])) as ex:
                nodes = list(ex.map(node_status, range(1, len(topo["nodes"]) + 1)))
            self.send(200, json.dumps({"topology": topo, "nodes": nodes, "job": JOB}))
        else:
            self.send(404, "{}")

    def do_POST(self):
        if self.path == "/api/apply":
            if JOB["busy"]:
                return self.send(409, json.dumps({"ok": False, "out": "ya hay un reinicio en curso"}))
            try:
                body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
                topo = valid_topology(json.loads(body))
            except Exception:
                return self.send(400, json.dumps({"ok": False, "out": "topología no válida"}))
            with open(TOPO, "w", encoding="utf-8", newline="\n") as f:
                json.dump(topo, f, indent=2)
            JOB.update(busy=True, msg="Preparando el reinicio…")
            threading.Thread(target=apply_job, daemon=True).start()
            return self.send(200, json.dumps({"ok": True}))
        m = re.fullmatch(r"/api/node/(\d+)/(stop|start)", self.path)
        if not m or not 1 <= int(m[1]) <= len(load_topology()["nodes"]):
            return self.send(404, "{}")
        n, action = int(m[1]), m[2]
        name = load_topology()["nodes"][n - 1]
        cmd = ["docker", "compose", action] + (["-t", "1"] if action == "stop" else []) + [name]
        try:
            run(cmd, 60)
            self.send(200, json.dumps({"ok": True}))
        except Exception as e:  # docker no instalado, timeout, etc.
            self.send(200, json.dumps({"ok": False, "out": str(e)}))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--no-browser", action="store_true")
    a = ap.parse_args()
    url = f"http://localhost:{a.port}"
    server = ThreadingHTTPServer(("127.0.0.1", a.port), Handler)
    print(f"Panel en {url}  (Ctrl+C para salir)")
    if not a.no_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
