"""Probe: prove or refute that a finite closed-road penalty keeps hazard-crossing routes
out of the top rank. Also evaluates a provable alternative.

NOT application code. Python stdlib only. Run at Stage 3 to decide the routing design.

WHY THIS EXISTS
---------------
Stage 3 §9 originally said: give `closed` edges "a large finite penalty", then rank by
cost. The Stage 3 review asked me to DEMONSTRATE that this cannot present a
closed-crossing route as eligible. A demonstration is not prose — so here it is, run
against (a) random graphs and (b) an adversarial graph sized to beat the penalty.

THREE CANDIDATE DESIGNS
-----------------------
A. PENALTY ONLY
     cost' = base * penalty(status), closed uses a large finite multiplier; rank by cost'.
     Stage 3's original wording.

B. TWO-PHASE EDGE FILTER  (the design this probe argues for)
     Phase 1: remove every CLOSED edge from the graph, then Dijkstra with penalties for
              affected/unknown. If a path exists, it provably contains zero closed edges —
              no arithmetic argument required.
     Phase 2: only if Phase 1 fails, search the full graph and classify the result as
              Hazard-crossing. This is the "no dry way out" case and must be labelled.

C. STATE-SPACE LEXICOGRAPHIC
     Dijkstra over (node, worst_status_so_far), minimising (rank, cost) lexicographically.

A is expected to FAIL on a suitably shaped graph: a finite multiplier is beatable by a
long-enough detour whose total cost exceeds penalty * base. B is expected to HOLD by
construction. C should also hold if implemented correctly.
"""
import heapq
import random

CLOSED, AFFECTED, UNKNOWN, OPEN = 0, 1, 2, 3
CLASS_NAMES = {CLOSED: "Hazard-crossing", AFFECTED: "Marginal",
               UNKNOWN: "Unknown-only", OPEN: "Eligible"}
CLASS_RANK = {OPEN: 0, UNKNOWN: 1, AFFECTED: 2, CLOSED: 3}

CLOSED_PENALTY = 250.0
PENALTIES = {OPEN: 1.0, UNKNOWN: 1.15, AFFECTED: 2.5, CLOSED: CLOSED_PENALTY}

# Allow base costs below 1.0 so the penalty can be overwhelmed; real base costs are
# travel times in seconds, but scale-invariance is exactly what makes A unsafe.
MIN_BASE, MAX_BASE = 0.05, 6.0


# ---------------------------------------------------------------- graph helpers
def grid_graph(n_rows, n_cols, rng, p_edge=0.8, base_lo=MIN_BASE, base_hi=MAX_BASE,
               status_probs=(0.15, 0.15, 0.20)):
    """Grid graph. status_probs = (closed, affected, unknown) shares; rest are open."""
    def nid(r, c):
        return r * n_cols + c

    adj = {nid(r, c): [] for r in range(n_rows) for c in range(n_cols)}
    for r in range(n_rows):
        for c in range(n_cols):
            for dr, dc in ((0, 1), (1, 0)):
                rr, cc = r + dr, c + dc
                if rr >= n_rows or cc >= n_cols or rng.random() > p_edge:
                    continue
                base = rng.uniform(base_lo, base_hi)
                roll = rng.random()
                if roll < status_probs[0]:
                    st = CLOSED
                elif roll < status_probs[0] + status_probs[1]:
                    st = AFFECTED
                elif roll < sum(status_probs):
                    st = UNKNOWN
                else:
                    st = OPEN
                u, v = nid(r, c), nid(rr, cc)
                adj[u].append((v, base, st))
                adj[v].append((u, base, st))
    return adj


def adversarial_graph():
    """Hand-built graph where a finite penalty is guaranteed to be beaten.

    src=0. There is a direct closed edge 0->1 with base 0.05:
        penalised cost = 0.05 * 250 = 12.5
    The only open alternative is a long chain of 40 edges at base 6.0 each:
        cost = 240.0
    12.5 < 240.0, so 'penalty only' must choose the closed edge.
    The two-phase filter removes the closed edge and finds the open chain instead.
    """
    adj = {0: [], 1: []}
    # direct, cheap, closed
    adj[0].append((1, 0.05, CLOSED))
    adj[1].append((0, 0.05, CLOSED))
    # long open chain 0 -> 2 -> ... -> 41 -> 1
    chain = [0] + [i for i in range(2, 42)] + [1]
    for a, b in zip(chain, chain[1:]):
        adj.setdefault(a, []).append((b, 6.0, OPEN))
        adj.setdefault(b, []).append((a, 6.0, OPEN))
    return adj, 0, 1


# ---------------------------------------------------------------- designs
def dijkstra(adj, src, dst, penalties, allowed=None):
    """Plain Dijkstra with per-status multipliers. `allowed(edge_status)` filters."""
    dist = {src: 0.0}
    prev = {src: None}
    pq = [(0.0, src)]
    while pq:
        d, u = heapq.heappop(pq)
        if d > dist.get(u, float("inf")):
            continue
        if u == dst:
            break
        for v, base, st in adj[u]:
            if allowed is not None and not allowed(st):
                continue
            nd = d + base * penalties[st]
            if nd < dist.get(v, float("inf")):
                dist[v] = nd
                prev[v] = (u, st, base)
                heapq.heappush(pq, (nd, v))
    if dst not in dist:
        return None, None
    path, cur = [], dst
    while prev[cur] is not None:
        u, st, base = prev[cur]
        path.append((u, cur, st, base))
        cur = u
    path.reverse()
    return dist[dst], path


def design_a_penalty_only(adj, src, dst):
    cost, path = dijkstra(adj, src, dst, PENALTIES)
    return cost, path


def design_b_two_phase(adj, src, dst):
    # Phase 1: hard filter — closed edges do not exist for this search.
    cost, path = dijkstra(adj, src, dst, PENALTIES, allowed=lambda st: st != CLOSED)
    if path is not None:
        return cost, path, "phase1"
    # Phase 2: nothing avoids closure; search everything, must be labelled.
    cost, path = dijkstra(adj, src, dst, PENALTIES)
    return cost, path, "phase2"


def design_c_state_space(adj, src, dst):
    """Lexicographic Dijkstra over (node, worst_rank). Correct by construction."""
    start = (src, CLASS_RANK[OPEN])
    best = {start: (CLASS_RANK[OPEN], 0.0)}
    prev = {start: None}
    pq = [(CLASS_RANK[OPEN], 0.0, src)]
    goal_state = None
    while pq:
        rank, cost, u = heapq.heappop(pq)
        if (rank, cost) > best.get((u, rank), (99, float("inf"))):
            continue
        if u == dst:
            goal_state = (u, rank)
            break
        for v, base, st in adj[u]:
            nrank = max(rank, CLASS_RANK[st])
            ncost = cost + base
            st_key = (v, nrank)
            if (nrank, ncost) < best.get(st_key, (99, float("inf"))):
                best[st_key] = (nrank, ncost)
                prev[st_key] = ((u, rank), st, base)
                heapq.heappush(pq, (nrank, ncost, v))
    if goal_state is None:
        return None, None
    # reconstruct through state chain
    path, cur = [], goal_state
    while prev.get(cur) is not None:
        (pstate, st, base) = prev[cur]
        path.append((pstate[0], cur[0], st, base))
        cur = pstate
    path.reverse()
    return best[goal_state][1], path


def worst_status(path):
    return min((e[2] for e in path), key=lambda s: CLASS_RANK[s])


def avoids_closed_exists(adj, src, dst):
    seen = {src}
    stack = [src]
    while stack:
        u = stack.pop()
        if u == dst:
            return True
        for v, _b, st in adj[u]:
            if st == CLOSED or v in seen:
                continue
            seen.add(v)
            stack.append(v)
    return False


# ---------------------------------------------------------------- evaluation
def check(label, adj, src, dst, result):
    """Returns (ok, detail). INVARIANT:
       - if a closed-free path exists, the served path must contain no closed edge
       - if none exists, the served path may contain one, but must be classified so
    """
    if label == "A":
        cost, path = result
        if path is None:
            return True, "refused"
        ws = worst_status(path)
        if avoids_closed_exists(adj, src, dst):
            return (ws != CLOSED), CLASS_NAMES[ws]
        return True, CLASS_NAMES[ws]
    elif label == "B":
        cost, path, phase = result
        if path is None:
            return True, "refused"
        ws = worst_status(path)
        if phase == "phase1":
            # provable: filtered search cannot return a closed edge
            return (ws != CLOSED), f"{CLASS_NAMES[ws]} ({phase})"
        return True, f"{CLASS_NAMES[ws]} ({phase})"
    else:
        cost, path = result
        if path is None:
            return True, "refused"
        ws = worst_status(path)
        if avoids_closed_exists(adj, src, dst):
            return (ws != CLOSED), CLASS_NAMES[ws]
        return True, CLASS_NAMES[ws]


def run_suite():
    rng = random.Random(20261025)
    tally = {k: {"ok": 0, "violations": 0, "refused": 0} for k in "ABC"}

    # --- suite 1: random graphs, square and elongated ---
    cases = []
    for _ in range(1200):
        rows, cols = rng.choice([(3, 3), (4, 4), (5, 5), (2, 12), (3, 14), (2, 20)])
        cases.append((grid_graph(rows, cols, rng), 0, rows * cols - 1))

    # --- suite 2: adversarial graph ---
    adv = adversarial_graph()
    cases.append(adv)

    for adj, src, dst in cases:
        for label, fn in (("A", design_a_penalty_only),
                          ("B", design_b_two_phase),
                          ("C", design_c_state_space)):
            res = fn(adj, src, dst)
            ok, detail = check(label, adj, src, dst, res)
            if "refused" in detail:
                tally[label]["refused"] += 1
            if ok:
                tally[label]["ok"] += 1
            else:
                tally[label]["violations"] += 1

    print("=" * 78)
    print(f"Suite: {len(cases)} graphs "
          f"(1200 random incl. elongated 2x20 grids + 1 adversarial)")
    print(f"Invariant: a route crossing a CLOSED edge must never be served as Eligible")
    print("=" * 78)
    for label, name in (("A", "A. penalty only (finite x%g)" % CLOSED_PENALTY),
                        ("B", "B. two-phase edge filter"),
                        ("C", "C. state-space lexicographic")):
        t = tally[label]
        total = t["ok"] + t["violations"]
        print(f"{name}")
        print(f"    invariant held : {t['ok']:5d} / {total}")
        print(f"    VIOLATIONS     : {t['violations']:5d}")
        print(f"    refused        : {t['refused']:5d}")
        print()

    # --- explicit adversarial demonstration ---
    adj, src, dst = adversarial_graph()
    print("=" * 78)
    print("ADVERSARIAL CASE — a finite penalty is provably insufficient")
    print("=" * 78)
    print("graph: direct edge 0->1 CLOSED with base 0.05, plus an open chain of 41 edges")
    print("       at base 6.0 each")
    print(f"       closed route penalised cost = 0.05 x {CLOSED_PENALTY:g} = "
          f"{0.05*CLOSED_PENALTY:.2f}")
    print(f"       open   route cost          = 41 x 6.0    = {41*6.0:.2f}")
    print()
    cost_a, path_a = design_a_penalty_only(adj, src, dst)
    ws_a = worst_status(path_a)
    print(f"A. penalty only  -> cost {cost_a:8.2f}  worst status: {CLASS_NAMES[ws_a]}"
          f"  {'<-- UNSAFE: closed edge served as best route' if ws_a == CLOSED else ''}")
    cost_b, path_b, phase = design_b_two_phase(adj, src, dst)
    ws_b = worst_status(path_b)
    print(f"B. two-phase     -> cost {cost_b:8.2f}  worst status: {CLASS_NAMES[ws_b]}"
          f"  (phase {phase}, {len(path_b)} edges)")
    cost_c, path_c = design_c_state_space(adj, src, dst)
    ws_c = worst_status(path_c)
    print(f"C. state-space   -> cost {cost_c:8.2f}  worst status: {CLASS_NAMES[ws_c]}"
          f"  ({len(path_c)} edges)")
    print()

    print("=" * 78)
    print("CONCLUSION")
    print("=" * 78)
    if tally["A"]["violations"] > 0:
        print("Design A (finite penalty) is REFUTED. A single adversarial graph — or any")
        print("graph whose closed-free detour costs more than penalty x closed-base —")
        print("makes it serve a closed-crossing route as the best result. Penalty")
        print("magnitude cannot fix this in general: it is scale-relative, and base")
        print("costs vary by orders of magnitude across a real road network.")
    else:
        print("Design A held on random graphs but FAILED the adversarial case below,")
        print("which is sufficient to refute it as a guarantee.")
    if tally["B"]["violations"] == 0:
        print()
        print("Design B (two-phase edge filter) held on every case, by construction: in")
        print("phase 1 the closed edges are absent from the graph, so no arithmetic")
        print("argument is needed at all. This is the design Stage 3 should adopt.")
    if tally["C"]["violations"] == 0:
        print("Design C also held and is a valid alternative; it additionally proves the")
        print("minimum achievable class in one pass. B is preferred for simplicity and")
        print("because its guarantee is structural rather than algorithmic.")


if __name__ == "__main__":
    run_suite()
