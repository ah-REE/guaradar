"""Throwaway feasibility probe: is the Guayaquil OSM road graph routable?

NOT application code, NOT a deliverable. Run manually; delete or ignore at will.
It exists to answer one question with measurement instead of assertion:
is a Guayaquil road graph connected enough for a route finder to be worth proposing?

Usage:  python3 research/graphcheck.py
Needs:  curl on PATH. No third-party Python packages.
"""
import json
import math
import subprocess
import sys
from collections import defaultdict, deque

BBOX = (-2.2300, -79.9300, -2.1400, -79.8600)  # central Guayaquil, ~10 x 8 km
QUERY = f'''[out:json][timeout:180];
way["highway"~"^(motorway|trunk|primary|secondary|tertiary|residential|unclassified|living_street)$"]{BBOX};
out body;
>;
out skel qt;'''

with open('/tmp/q.txt', 'w') as f:
    f.write(QUERY)

proc = subprocess.run([
    'curl', '-s', '-w', '\nHTTP=%{http_code}', '--max-time', '240',
    '-A', 'GuaRadar-research/0.1 (hackathon feasibility check)',
    '-X', 'POST', 'https://overpass-api.de/api/interpreter',
    '--data-urlencode', 'data@/tmp/q.txt'], capture_output=True, text=True)
if proc.returncode != 0:
    print("curl failed", proc.returncode, proc.stderr[:400])
    sys.exit(1)

raw = proc.stdout
if 'HTTP=' in raw:
    body, _, code = raw.rpartition('\nHTTP=')
    print(f"overpass http status: {code}")
else:
    body = raw

if not body.strip().startswith('{'):
    print("non-JSON response, first 400 bytes:")
    print(body[:400])
    sys.exit(1)

d = json.loads(body)
els = d['elements']
ways = [e for e in els if e['type'] == 'way']
nodes = {e['id']: e for e in els if e['type'] == 'node'}
print(f"ways fetched: {len(ways)}   nodes fetched: {len(nodes)}")
print(f"osm timestamp: {d['osm3s']['timestamp_osm_base']}")


def hav(a, b):
    """Great-circle distance in metres between two (lat, lon) tuples."""
    R = 6371000.0
    la1, lo1 = math.radians(a[0]), math.radians(a[1])
    la2, lo2 = math.radians(b[0]), math.radians(b[1])
    dla, dlo = la2 - la1, lo2 - lo1
    h = math.sin(dla / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin(dlo / 2) ** 2
    return 2 * R * math.asin(math.sqrt(h))


adj = defaultdict(set)
length_total = 0.0
missing_coords = 0
by_type = defaultdict(int)

for w in ways:
    by_type[w['tags'].get('highway', '?')] += 1
    nds = w['nodes']
    for a, b in zip(nds, nds[1:]):
        adj[a].add(b)
        adj[b].add(a)
        ca, cb = nodes.get(a), nodes.get(b)
        if ca and cb:
            length_total += hav((ca['lat'], ca['lon']), (cb['lat'], cb['lon']))
        else:
            missing_coords += 1

seg_count = sum(len(s) for s in adj.values()) / 2
print(f"distinct graph nodes : {len(adj)}")
print(f"undirected segments  : {seg_count:.0f}")
print(f"total network length : {length_total/1000:.1f} km")
print(f"segments missing coords: {missing_coords}")
print(f"way types: {dict(sorted(by_type.items(), key=lambda x: -x[1]))}")

seen = set()
comps = []
for n in adj:
    if n in seen:
        continue
    q = deque([n])
    seen.add(n)
    members = []
    while q:
        u = q.popleft()
        members.append(u)
        for v in adj[u]:
            if v not in seen:
                seen.add(v)
                q.append(v)
    comps.append(members)
comps.sort(key=len, reverse=True)

tot = len(adj)
print(f"\ncomponents: {len(comps)}")
print(f"largest: {len(comps[0])} nodes = {100*len(comps[0])/tot:.1f}% of nodes")
print(f"top 5 sizes: {[len(c) for c in comps[:5]]}")

deg = [len(adj[n]) for n in adj]
print(f"isolated nodes (degree 0): {sum(1 for x in deg if x == 0)}")
print(f"nodes with degree>=3     : {sum(1 for x in deg if x >= 3)} = "
      f"{100*sum(1 for x in deg if x >= 3)/tot:.1f}%")
print(f"mean degree: {sum(deg)/len(deg):.2f}")


def coord(i):
    n = nodes.get(i)
    return (n['lat'], n['lon']) if n else None


big = comps[0]
pts = [(i, coord(i)) for i in big]
pts = [p for p in pts if p[1]]
pts.sort(key=lambda p: p[1][0])
a, b = pts[0], pts[-1]
straight = hav(a[1], b[1])
print("\nBFS route test inside largest component:")
print(f"  origin      {a[1]}")
print(f"  destination {b[1]}")
print(f"  straight-line {straight/1000:.2f} km")


def bfs(src, dst):
    prev = {src: None}
    q = deque([src])
    while q:
        u = q.popleft()
        if u == dst:
            break
        for v in adj[u]:
            if v not in prev:
                prev[v] = u
                q.append(v)
    if dst not in prev:
        return None
    path = []
    cur = dst
    while cur is not None:
        path.append(cur)
        cur = prev[cur]
    return path[::-1]


path = bfs(a[0], b[0])
if path is None:
    print("  NO ROUTE FOUND between those two points")
else:
    pl = 0.0
    for x, y in zip(path, path[1:]):
        cx, cy = coord(x), coord(y)
        if cx and cy:
            pl += hav(cx, cy)
    print(f"  ROUTE FOUND: {len(path)} nodes, {pl/1000:.2f} km network length")
    print(f"  detour factor: {pl/straight:.2f}x straight line")
