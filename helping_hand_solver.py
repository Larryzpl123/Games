#!/usr/bin/env python3
"""BFS solver for Helping Hand levels. Run: python3 solver.py
Prints the optimal move count for every level (this is where the "par" numbers came from)."""
import time
from collections import deque
import helping_hand as hh


def solve(level, limit=3_000_000):
    start = level.start
    k0 = start.key(level)
    seen = {k0: None}
    q = deque([(start, k0)])
    while q:
        st, k = q.popleft()
        for dname in ("left", "right", "up", "down"):
            new, _, moved = hh.move(level, st, dname)
            if not moved or new.dead:
                continue
            nk = new.key(level)
            if nk in seen:
                continue
            seen[nk] = (k, dname)
            if new.solved(level):
                path, cur = [], nk
                while seen[cur] is not None:
                    cur, d = seen[cur]
                    path.append(d)
                return path[::-1], len(seen)
            q.append((new, nk))
            if len(seen) > limit:
                return None, len(seen)
    return None, len(seen)


if __name__ == "__main__":
    for i, data in enumerate(hh.LEVELS):
        lv = hh.Level(data)
        t = time.time()
        path, n = solve(lv)
        if path is None:
            print(f"{i+1}. {lv.name}: no solution found ({n} states)")
        else:
            print(f"{i+1}. {lv.name}: optimal = {len(path)} moves (par {lv.par}), "
                  f"{n} states, {time.time()-t:.1f}s\n   {' '.join(path)}")
