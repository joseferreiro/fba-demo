#!/usr/bin/env python3
"""
Cada nodo tiene sus propios quorum slices, definidos en `topology.json` (editable):
    "node1": {"validators": ["node1", "node2", "node3"], "threshold": 2}   # slice = 2 de esos 3

Uso:
  python fba_docker_demo.py                    # crea ./fba-demo con 6 nodos (slice = 5 de 6)
  python fba_docker_demo.py --nodes 6          # 6 nodos (reescribe la topología por defecto)
  python fba_docker_demo.py --out fba-demo     # tras editar topology.json: regenera las configuraciones
  python fba_docker_demo.py --dry-run          # claves falsas, solo para revisar los ficheros

Las claves se guardan en keys.json y se reutilizan; solo se generan las de los nodos nuevos.
"""
import argparse
import json
import os
import re
import shutil
import stat
import subprocess
import sys

IMAGE = "stellar/stellar-core:latest"
PASSPHRASE = "FBA Demo Network ; October 2026"
MAX_NODES = 9


# Genera una clave de Stellar para un nodo concreto.
def gen_key(dry, i):
    if dry:
        return "S" + chr(65 + i % 26) * 55, "G" + chr(65 + i % 26) * 55
    out = subprocess.run(["docker", "run", "--rm", IMAGE, "gen-seed"],
                         capture_output=True, text=True, check=True).stdout
    seed, pub = re.search(r"S[A-Z2-7]{55}", out), re.search(r"G[A-Z2-7]{55}", out)
    if not (seed and pub):
        sys.exit("No pude leer la clave de `gen-seed`. Salida:\n" + out)
    return seed.group(0), pub.group(0)


# Topología por defecto: todos los nodos confían en todos los nodos del conjunto y
# el umbral se fija en una fracción mayoritaria (2*n/3 + 1).
def default_topology(n):
    names = [f"node{i}" for i in range(1, n + 1)]
    t = (2 * n) // 3 + 1
    return {"_ayuda": "slices[nodo] = {validators: nodos en los que confía (él mismo siempre cuenta), "
                      "threshold: cuántos de ellos bastan}. Tras editar: python fba_docker_demo.py --out . "
                      "y reiniciar la red con down -v / up -d.",
            "nodes": names,
            "slices": {x: {"validators": list(names), "threshold": t} for x in names}}


# nodos únicos, umbrales válidos y sin referencias a nodos inexistentes.
def validate(topo):
    nodes = topo.get("nodes", [])
    if not 1 <= len(nodes) <= MAX_NODES or len(set(nodes)) != len(nodes):
        sys.exit(f"topology.json: 'nodes' debe tener entre 1 y {MAX_NODES} nombres distintos.")
    slices = {}
    for x in nodes:
        s = topo.get("slices", {}).get(x)
        if not s:
            sys.exit(f"topology.json: falta el slice de {x}.")
        bad = [y for y in s["validators"] if y not in nodes]
        if bad:
            sys.exit(f"topology.json: {x} confía en nodos que no existen: {bad}")
        v = list(dict.fromkeys(s["validators"]))
        if x not in v:
            v.insert(0, x)
        t = int(s["threshold"])
        if not 1 <= t <= len(v):
            sys.exit(f"topology.json: el umbral de {x} ({t}) debe estar entre 1 y {len(v)}.")
        slices[x] = {"validators": v, "threshold": t}
    return nodes, slices


def percent(t, n):
    return min(100, -(-100 * (t - 1) // n) + 1)


# Configuración de cada nodo
def config(me, keys, nodes, slices):
    s = slices[me]
    peers = ", ".join(f'"{x}:11625"' for x in nodes if x != me)

    members = ",\n".join(f'"${me}"' if x == me else f'"{keys[x]["pub"]} {x}"' for x in s["validators"])
    hist = ""
    for x in nodes:
        hist += f'[HISTORY.{x}]\nget="cp /archive/{x}/{{0}} {{1}}"\n'
        if x == me:
            hist += f'put="cp {{0}} /archive/{x}/{{1}}"\nmkdir="mkdir -p /archive/{x}/{{0}}"\n'
        hist += "\n"
    return f'''NETWORK_PASSPHRASE="{PASSPHRASE}"
    NODE_SEED="{keys[me]["seed"]} {me}"
    NODE_IS_VALIDATOR=true
    PEER_PORT=11625
    HTTP_PORT=11626
    PUBLIC_HTTP_PORT=true
    LOG_FILE_PATH=""
    DATABASE="sqlite3:///data/stellar.db"
    BUCKET_DIR_PATH="/data/buckets"
    KNOWN_PEERS=[{peers}]
    UNSAFE_QUORUM=true
    FAILURE_SAFETY=0

    # Quorum slice de {me}: {s["threshold"]} de {len(s["validators"])}
    [QUORUM_SET]
    THRESHOLD_PERCENT={percent(s["threshold"], len(s["validators"]))}
    VALIDATORS=[
    {members}
    ]

    {hist}'''


def compose(nodes):
    svc = "".join(f'''  {x}:
    image: {IMAGE}
    user: root
    entrypoint: ["/bin/sh", "/start.sh"]
    hostname: {x}
    environment:
      NODE: {x}
    volumes:
      - ./start.sh:/start.sh:ro
      - ./configs/{x}:/etc/stellar:ro
      - {x}-data:/data
      - archive:/archive
    ports:
      - "{11626 + i}:11626"
''' for i, x in enumerate(nodes))
    vols = "".join(f"  {x}-data:\n" for x in nodes)
    return f"services:\n{svc}\nvolumes:\n{vols}  archive:\n"


START = '''#!/bin/sh
set -e
CFG=/etc/stellar/stellar-core.cfg
if [ ! -f /data/.initialized ]; then
  stellar-core --conf "$CFG" new-db
  stellar-core --conf "$CFG" new-hist "$NODE"
  stellar-core --conf "$CFG" force-scp
  touch /data/.initialized
fi
exec stellar-core --conf "$CFG" run
'''

DEMO = r'''#!/usr/bin/env python3
"""Uso: python demo.py status | watch | quorum N | stop N | start N | logs N   (N = 1..__N__)"""
import json
import os
import subprocess
import sys
import time
import urllib.request

N = __N__


def port(n):
    return 11625 + int(n)


def get(n, path, timeout=2):
    with urllib.request.urlopen(f"http://localhost:{port(n)}/{path}", timeout=timeout) as r:
        return json.load(r)


def info(n):
    try:
        i = get(n, "info")["info"]
        return f"{i['state']} | ledger {i['ledger']['num']}"
    except Exception:
        return "(caido)"


def status():
    for n in range(1, N + 1):
        print(f"node{n}: {info(n)}")


def dc(*args):
    subprocess.run(["docker", "compose", *args])


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    n = sys.argv[2] if len(sys.argv) > 2 else "1"
    if cmd == "status":
        status()
    elif cmd == "watch":
        try:
            while True:
                os.system("cls" if os.name == "nt" else "clear")
                print(time.strftime("%H:%M:%S"))
                status()
                time.sleep(2)
        except KeyboardInterrupt:
            pass
    elif cmd == "quorum":
        print(json.dumps(get(n, "quorum?transitive=true", 5), indent=2))
    elif cmd == "stop":
        dc("stop", "-t", "1", f"node{n}")
    elif cmd == "start":
        dc("start", f"node{n}")
    elif cmd == "logs":
        dc("logs", "-f", "--tail", "40", f"node{n}")
    else:
        print(__doc__)


main()
'''

README = '''# Demo FBA con stellar-core en Docker

Red privada de {n} validadores. Cada nodo tiene sus propios quorum slices, definidos en `topology.json`.

## Arranque
    docker compose up -d
    python fba_dashboard.py      # panel gráfico en http://localhost:8080 (copiar aquí fba_dashboard.py)

## Cambiar slices o añadir nodos
1. Edita `topology.json` (o usa el editor del panel) y ejecuta `python fba_docker_demo.py --out .`
2. Reinicia la red desde cero: `docker compose down -v --remove-orphans` y `docker compose up -d`
   (todos los nodos arrancan en el génesis; el número de ledger vuelve a empezar).
Para pasar a otro número de nodos: `python fba_docker_demo.py --out . --nodes 6` (reescribe topology.json).

## Consola
`python demo.py status | watch | quorum N | stop N | start N | logs N`

## Si algo falla
- `docker compose logs node1` : el primer error suele indicar qué clave no acepta tu versión de stellar-core.
- Fijar una versión concreta de la imagen (IMAGE en el generador).
'''


def write(path, text, exe=False):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    if exe:
        os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default="fba-demo")
    ap.add_argument("--nodes", type=int, help=f"número de nodos (1-{MAX_NODES}); reescribe topology.json")
    ap.add_argument("--dry-run", action="store_true", help="claves falsas; solo para revisar los ficheros")
    a = ap.parse_args()

    topo_path, keys_path = os.path.join(a.out, "topology.json"), os.path.join(a.out, "keys.json")
    if a.nodes is not None or not os.path.exists(topo_path):
        topo = default_topology(a.nodes or 6)
        write(topo_path, json.dumps(topo, indent=2, ensure_ascii=False) + "\n")
    else:
        with open(topo_path, encoding="utf-8") as f:
            topo = json.load(f)
    nodes, slices = validate(topo)

    keys = {}
    if os.path.exists(keys_path) and not a.dry_run:
        with open(keys_path, encoding="utf-8") as f:
            keys = json.load(f)
    for i, x in enumerate(nodes):
        if x not in keys:
            seed, pub = gen_key(a.dry_run, i)
            keys[x] = {"seed": seed, "pub": pub}
    if not a.dry_run:
        write(keys_path, json.dumps(keys, indent=2) + "\n")

    for x in nodes:
        write(f"{a.out}/configs/{x}/stellar-core.cfg", config(x, keys, nodes, slices))
    write(f"{a.out}/docker-compose.yml", compose(nodes))
    write(f"{a.out}/start.sh", START, exe=True)
    write(f"{a.out}/demo.py", DEMO.replace("__N__", str(len(nodes))))
    write(f"{a.out}/README.md", README.format(n=len(nodes)))
    here = os.path.dirname(os.path.abspath(__file__))
    for name in ("fba_docker_demo.py", "fba_dashboard.py"):
        src, dst = os.path.join(here, name), os.path.join(a.out, name)
        if os.path.exists(src) and os.path.abspath(src) != os.path.abspath(dst):
            shutil.copy(src, dst)
    print(f"Generado en {a.out}/ ({len(nodes)} nodos). " + (
        "(claves falsas: no arrancará)" if a.dry_run else
        f"Siguiente: cd {a.out} && docker compose down -v --remove-orphans && docker compose up -d"))


if __name__ == "__main__":
    main()
