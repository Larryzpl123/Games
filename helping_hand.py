#!/usr/bin/env python3
"""
Helping Hand  -  pygame version
================================
Run:   python3 -m pip install pygame
       python3 helping_hand.py
Keep this file next to the "Game Assets" folder.

Base game (Ludo Lodge Project 2): hand, walls, crates, sliding crates, pits,
red switch + red door, goal, restart (R), multiple levels.
Challenges 1-5: green switch/door, move counter, title screen (and return to it
after the last level), green crates, multiple hands moving simultaneously.
Revisions: particle effects (visual), undo / timed spikes / teleporters
(gameplay), star rating against par (rules).
"""
# ---------------------------------------------------------------------------
#  Helping Hand - shared rules engine (pure Python, no pygame here)
#  Used by helping_hand.py (the game) and by solver.py (BFS verification).
# ---------------------------------------------------------------------------
#  Map legend
#    #  wall            .  floor            H  hand (any number)
#    C  crate           S  sliding crate    G  green crate
#    O  pit             X  goal
#    r  red switch      R  red door         g  green switch     D  green door
#    ^  spike trap (cycle of 4 moves: down, WARN, up, up)
#    1  teleporter pair 1   2  teleporter pair 2
# ---------------------------------------------------------------------------

DIRS = {"left": (-1, 0), "right": (1, 0), "up": (0, -1), "down": (0, 1)}
SPIKE_PERIOD = 4            # moves per full spike cycle
CRATE, SLIDING, GREEN = "crate", "sliding", "green"


def spike_phase(moves):
    """0 = down, 1 = down but WARNING (rises on next move), 2/3 = up."""
    return moves % SPIKE_PERIOD


def spikes_up(moves):
    return spike_phase(moves) >= 2


class Level:
    def __init__(self, data):
        self.name = data["name"]
        self.par = data.get("par", 0)
        self.hint = data.get("hint", "")
        rows = data["map"]
        self.h = len(rows)
        self.w = max(len(r) for r in rows)
        self.walls, self.pits, self.goals, self.spikes = set(), set(), set(), set()
        self.red_switches, self.green_switches = set(), set()
        self.red_doors, self.green_doors = set(), set()
        self.teleporters = {}          # pos -> partner pos
        self.tele_id = {}              # pos -> "1" / "2"
        hands, crates, tele = [], {}, {}
        for y, row in enumerate(rows):
            for x, ch in enumerate(row):
                p = (x, y)
                if ch == "#":
                    self.walls.add(p)
                elif ch == "H":
                    hands.append(p)
                elif ch == "C":
                    crates[p] = CRATE
                elif ch == "S":
                    crates[p] = SLIDING
                elif ch == "G":
                    crates[p] = GREEN
                elif ch == "O":
                    self.pits.add(p)
                elif ch == "r":
                    self.red_switches.add(p)
                elif ch == "R":
                    self.red_doors.add(p)
                elif ch == "g":
                    self.green_switches.add(p)
                elif ch == "D":
                    self.green_doors.add(p)
                elif ch == "X":
                    self.goals.add(p)
                elif ch == "^":
                    self.spikes.add(p)
                elif ch in "12":
                    tele.setdefault(ch, []).append(p)
        for ch, ps in tele.items():
            if len(ps) != 2:
                raise ValueError(f"{self.name}: teleporter {ch} needs exactly 2 tiles")
            a, b = ps
            self.teleporters[a], self.teleporters[b] = b, a
            self.tele_id[a] = self.tele_id[b] = ch
        if len(self.goals) < len(hands):
            raise ValueError(f"{self.name}: fewer goals than hands")
        self.start = State(hands, crates)

    # --- door / switch logic --------------------------------------------
    def red_open(self, crates):
        return any(p in crates for p in self.red_switches)

    def green_open(self, crates):
        return any(p in crates for p in self.green_switches)

    def solid(self, p, red, green):
        """True if p is a wall or a closed door."""
        if p in self.walls:
            return True
        if p in self.red_doors and not red:
            return True
        if p in self.green_doors and not green:
            return True
        return False


class State:
    __slots__ = ("hands", "crates", "filled", "moves", "dead", "sprites")

    def __init__(self, hands, crates, filled=None, moves=0, dead=False, sprites=None):
        self.hands = list(hands)
        self.crates = dict(crates)
        self.filled = set(filled or ())
        self.moves = moves
        self.dead = dead
        self.sprites = list(sprites) if sprites else ["hand"] * len(self.hands)

    def copy(self):
        return State(self.hands, self.crates, self.filled, self.moves, self.dead, self.sprites)

    def key(self, level):
        phase = spike_phase(self.moves) if level.spikes else 0
        return (tuple(sorted(self.hands)), tuple(sorted(self.crates.items())),
                tuple(sorted(self.filled)), phase)

    def solved(self, level):
        return not self.dead and all(h in level.goals for h in self.hands)


def _free_for_crate(level, st, p, red, green):
    return not level.solid(p, red, green) and p not in st.crates and p not in st.hands


def _try_teleport(level, st, p, events, who):
    """Return the tile an object entering p ends up on (partner if free)."""
    if p in level.teleporters:
        ex = level.teleporters[p]
        if ex not in st.crates and ex not in st.hands:
            events.append(("teleport", who, p, ex))
            return ex
    return p


def _place_crate(level, st, p, ctype, events):
    if p in level.pits and p not in st.filled:
        st.filled.add(p)
        events.append(("fill", p))
        return
    p = _try_teleport(level, st, p, events, "crate")
    st.crates[p] = ctype


def _slide(level, st, start, d, events):
    """Sliding crate: keep moving until wall/door/crate/hand; stop in a pit."""
    cur = start
    while True:
        red, green = level.red_open(st.crates), level.green_open(st.crates)
        nxt = (cur[0] + d[0], cur[1] + d[1])
        if not _free_for_crate(level, st, nxt, red, green):
            break
        events.append(("slide", cur, nxt))
        cur = nxt
        if cur in level.pits and cur not in st.filled:
            st.filled.add(cur)
            events.append(("fill", cur))
            return
        cur = _try_teleport(level, st, cur, events, "crate")
    st.crates[cur] = SLIDING


def move(level, st, dname):
    """Apply one key press. Returns (new_state, events, moved_any)."""
    d = DIRS[dname]
    new = st.copy()
    events = []
    # front-most hands (in the direction of travel) move first, so lines move together
    order = sorted(range(len(new.hands)),
                   key=lambda i: -(new.hands[i][0] * d[0] + new.hands[i][1] * d[1]))
    moved_any = False
    for i in order:
        p = new.hands[i]
        q = (p[0] + d[0], p[1] + d[1])
        red, green = level.red_open(new.crates), level.green_open(new.crates)
        if level.solid(q, red, green):
            continue
        if q in level.pits and q not in new.filled:
            continue
        if q in new.hands:
            continue
        ctype = new.crates.get(q)
        if ctype is not None and not (ctype == GREEN and not green):
            # push
            r = (q[0] + d[0], q[1] + d[1])
            if not _free_for_crate(level, new, r, red, green):
                continue
            del new.crates[q]
            events.append(("push", ctype, q, r))
            if ctype == SLIDING:
                _slide(level, new, q, d, events)
            else:
                _place_crate(level, new, r, ctype, events)
            new.sprites[i] = "push_" + dname
        else:
            new.sprites[i] = "hand"
        events.append(("step", i, p, q))
        new.hands[i] = _try_teleport(level, new, q, events, "hand")
        moved_any = True
    if moved_any:
        new.moves += 1
        if level.spikes and spikes_up(new.moves):
            for h in new.hands:
                if h in level.spikes:
                    new.dead = True
                    events.append(("spike", h))
    return new, events, moved_any


def stars_for(moves, par):
    if moves <= par:
        return 3
    if moves <= par + max(2, par // 2):
        return 2
    return 1


LEVELS = [
    {
        "name": "First Steps",
        "par": 7,
        "hint": "Arrow keys move. Push the crate into the pit to cross.",
        "map": [
            "##########",
            "#H.......#",
            "#...C....#",
            "#........#",
            "####O#####",
            "#...X....#",
            "##########",
        ],
    },
    {
        "name": "Red Switch",
        "par": 24,
        "hint": "Sliding crates slide until they hit something. A crate on a red switch opens red doors.",
        "map": [
            "############",
            "#H.....R...#",
            "#.....C#...#",
            "#.S..r.#.X.#",
            "#......#...#",
            "#......#...#",
            "############",
        ],
    },
    {
        "name": "Green Light",
        "par": 12,
        "hint": "Green crates are ghosts until a crate sits on a green switch.",
        "map": [
            "############",
            "#H.....#####",
            "#.C..G.D.OX#",
            "#..g...#####",
            "#......#####",
            "############",
        ],
    },
    {
        "name": "Portal",
        "par": 12,
        "hint": "Anything that steps on a portal comes out of its twin (if the twin is free).",
        "map": [
            "############",
            "#H....#....#",
            "#.....#1...#",
            "#.....#...O#",
            "#.S1..#..#X#",
            "#.....#..###",
            "############",
        ],
    },
    {
        "name": "Spikes",
        "par": 15,
        "hint": "Spikes rise every 2 moves. Don't stand on a raised spike. Z undoes.",
        "map": [
            "############",
            "#H....#....#",
            "#.##..#..#.#",
            "#....^^....#",
            "#.##..#..#.#",
            "#.....#...X#",
            "############",
        ],
    },
    {
        "name": "Two Hands",
        "par": 15,
        "hint": "Both hands move together. Every hand must stand on a goal.",
        "map": [
            "############",
            "#H....##...#",
            "#.....##...#",
            "#.C...##.X.#",
            "#H....##...#",
            "#....O..X..#",
            "############",
        ],
    },
    {
        "name": "Helping Hands",
        "par": 32,
        "hint": "Everything at once. Good luck.",
        "map": [
            "##############",
            "#H.....#######",
            "#..C...#^G.O.#",
            "#..r...R^###X#",
            "#......#######",
            "#.S....#######",
            "#H.....#######",
            "#.g1...##1OX##",
            "##############",
        ],
    },
]


# ---------------------------------------------------------------------------
#  pygame front end
# ---------------------------------------------------------------------------
import os, sys, math, random, time

TILE = 32
SCALE = 2
T = TILE * SCALE          # on-screen tile size
HUD_H = 60
ANIM_MS = 110
ASSET_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Game Assets")

SPRITE_FILES = {
    "hand": "hand.png", "push_left": "hand_push_left.png", "push_right": "hand_push_right.png",
    "push_up": "hand_push_up.png", "push_down": "hand_push_down.png",
    "wall": "wall.png", "floor": "floor.png", "crate": "crate.png", "sliding": "sliding_crate.png",
    "green": "green_crate.png", "green_inactive": "green_crate_inactive.png",
    "pit": "pit.png", "pit_filled": "pit_filled.png", "goal": "goal.png",
    "red_switch": "red_switch.png", "red_door": "red_door.png", "red_door_open": "red_door_open.png",
    "green_switch": "green_switch.png", "green_door": "green_door.png", "green_door_open": "green_door_open.png",
    "spike_down": "spike_down.png", "spike_warn": "spike_warn.png", "spike_up": "spike_up.png",
    "portal_1": "portal_1.png", "portal_2": "portal_2.png",
}

BG = (28, 29, 38)
HUD_BG = (18, 19, 26)
WHITE = (240, 240, 245)
GREY = (150, 152, 165)
YELLOW = (250, 220, 80)
RED = (240, 90, 90)


class Particle:
    __slots__ = ("x", "y", "vx", "vy", "life", "max_life", "color", "size", "grav", "shape")

    def __init__(self, x, y, vx, vy, life, color, size, grav=0.0, shape="rect"):
        self.x, self.y, self.vx, self.vy = x, y, vx, vy
        self.life = self.max_life = life
        self.color, self.size, self.grav, self.shape = color, size, grav, shape


class FloatText:
    __slots__ = ("x", "y", "text", "life", "color")

    def __init__(self, x, y, text, color):
        self.x, self.y, self.text, self.life, self.color = x, y, text, 0.9, color


def lerp(a, b, t):
    return a + (b - a) * t


class Game:
    def __init__(self):
        import pygame
        self.pg = pygame
        pygame.init()
        pygame.display.set_caption("Helping Hand")
        self.levels = [Level(d) for d in LEVELS]
        maxw = max(l.w for l in self.levels) * T
        maxh = max(l.h for l in self.levels) * T + HUD_H + 8 + 40
        self.screen = pygame.display.set_mode((maxw, maxh))
        self.W, self.H = maxw, maxh
        self.clock = pygame.time.Clock()
        self.font = pygame.font.Font(None, 30)
        self.small = pygame.font.Font(None, 22)
        self.big = pygame.font.Font(None, 72)
        self.img = {}
        for key, fn in SPRITE_FILES.items():
            surf = pygame.image.load(os.path.join(ASSET_DIR, fn)).convert_alpha()
            self.img[key] = pygame.transform.scale(surf, (T, T))
        self.scene = "title"
        self.level_index = 0
        self.stars = []          # stars earned per level
        self.particles = []
        self.texts = []
        self.hand_anim = {}      # hand index -> (from_pos, t0)
        self.crate_anim = {}     # final pos -> (from_pos, t0, dur)
        self.ghosts = []         # (img_key, from, to, t0, dur) - crates falling into pits
        self.prev_doors = (False, False)
        self.shake = 0.0
        self.time = 0.0

    # ---------------- level handling ----------------
    def load_level(self, i):
        self.level_index = i
        self.level = self.levels[i]
        self.state = self.level.start.copy()
        self.undo_stack = []
        self.hand_anim, self.crate_anim, self.ghosts = {}, {}, []
        self.particles, self.texts = [], []
        self.prev_doors = (self.level.red_open(self.state.crates), self.level.green_open(self.state.crates))
        self.ox = (self.W - self.level.w * T) // 2
        self.oy = HUD_H + 8 + (self.H - HUD_H - 48 - self.level.h * T) // 2
        self.scene = "play"
        self.clear_time = None

    def px(self, p):
        """grid pos -> top-left pixel"""
        return self.ox + p[0] * T, self.oy + p[1] * T

    def center(self, p):
        x, y = self.px(p)
        return x + T / 2, y + T / 2

    # ---------------- input ----------------
    def try_move(self, dname):
        if self.state.dead:
            return
        new, events, moved = move(self.level, self.state, dname)
        if not moved:
            return
        self.undo_stack.append(self.state)
        self.state = new
        now = time.time()
        for e in events:
            k = e[0]
            if k == "step":
                _, i, p, q = e
                self.hand_anim[i] = (p, now)
                self.emit_dust(self.center(p), 3, (80, 82, 96))
            elif k == "push":
                _, ctype, q, r = e
                if ctype != SLIDING:
                    self.crate_anim[r] = (q, now, ANIM_MS)
                self.emit_dust(self.center(q), 10, (120, 100, 70))
            elif k == "slide":
                _, a, b = e
                # extend the animation from wherever this crate started sliding
                start, t0, dur = self.crate_anim.pop(a, (a, now, 0))
                dist = abs(b[0] - start[0]) + abs(b[1] - start[1])
                self.crate_anim[b] = (start, t0, max(ANIM_MS, 60 * dist))
                self.emit_dust(self.center(a), 2, (120, 100, 70))
            elif k == "fill":
                _, p = e
                start, t0, dur = self.crate_anim.pop(p, (p, now, ANIM_MS))
                self.ghosts.append(("crate", start, p, t0, dur))
                self.emit_splash(self.center(p))
                self.texts.append(FloatText(*self.center(p), "FILLED!", (200, 170, 120)))
            elif k == "teleport":
                _, who, a, b = e
                self.emit_portal(self.center(a))
                self.emit_portal(self.center(b))
                if who == "crate":
                    self.crate_anim.pop(a, None)
                    self.crate_anim.pop(b, None)
            elif k == "spike":
                _, p = e
                self.emit_burst(self.center(p), (240, 80, 80), 30)
                self.shake = 0.35
                self.texts.append(FloatText(*self.center(p), "OUCH!", RED))
        # hands that teleported should not tween across the map
        for i, h in enumerate(self.state.hands):
            if i in self.hand_anim:
                fp = self.hand_anim[i][0]
                if abs(fp[0] - h[0]) + abs(fp[1] - h[1]) > 1:
                    del self.hand_anim[i]
        # door open / close puffs
        doors = (self.level.red_open(self.state.crates), self.level.green_open(self.state.crates))
        if doors[0] != self.prev_doors[0]:
            for p in self.level.red_doors:
                self.emit_burst(self.center(p), (255, 120, 120), 14)
        if doors[1] != self.prev_doors[1]:
            for p in self.level.green_doors:
                self.emit_burst(self.center(p), (120, 255, 140), 14)
            for p, ct in self.state.crates.items():
                if ct == GREEN:
                    self.emit_burst(self.center(p), (120, 255, 140), 8)
        self.prev_doors = doors
        if self.state.solved(self.level):
            self.scene = "clear"
            self.clear_time = time.time()
            self.earned = stars_for(self.state.moves, self.level.par)
            for h in self.state.hands:
                self.emit_sparkle(self.center(h))

    def undo(self):
        if self.undo_stack:
            self.state = self.undo_stack.pop()
            self.hand_anim, self.crate_anim, self.ghosts = {}, {}, []
            self.prev_doors = (self.level.red_open(self.state.crates), self.level.green_open(self.state.crates))
            self.texts.append(FloatText(self.W / 2, self.oy + 20, "UNDO", GREY))

    # ---------------- particles ----------------
    def emit_dust(self, c, n, color):
        for _ in range(n):
            a = random.uniform(0, math.tau)
            s = random.uniform(10, 40)
            self.particles.append(Particle(c[0], c[1] + T * 0.3, math.cos(a) * s, math.sin(a) * s - 10,
                                           random.uniform(0.25, 0.5), color, random.randint(2, 5)))

    def emit_splash(self, c):
        for _ in range(26):
            a = random.uniform(-math.pi, 0)
            s = random.uniform(60, 180)
            self.particles.append(Particle(c[0], c[1], math.cos(a) * s * 0.6, math.sin(a) * s,
                                           random.uniform(0.4, 0.8), random.choice([(150, 110, 60), (110, 80, 45), (200, 160, 100)]),
                                           random.randint(3, 6), grav=420))

    def emit_burst(self, c, color, n):
        for _ in range(n):
            a = random.uniform(0, math.tau)
            s = random.uniform(40, 160)
            self.particles.append(Particle(c[0], c[1], math.cos(a) * s, math.sin(a) * s,
                                           random.uniform(0.3, 0.7), color, random.randint(2, 5), grav=120))

    def emit_portal(self, c):
        for i in range(18):
            a = i / 18 * math.tau
            self.particles.append(Particle(c[0] + math.cos(a) * 18, c[1] + math.sin(a) * 18,
                                           math.cos(a + 1.2) * 90, math.sin(a + 1.2) * 90,
                                           0.5, (140, 170, 255), 3, shape="circle"))

    def emit_sparkle(self, c):
        for _ in range(40):
            a = random.uniform(0, math.tau)
            s = random.uniform(30, 200)
            self.particles.append(Particle(c[0], c[1], math.cos(a) * s, math.sin(a) * s,
                                           random.uniform(0.6, 1.3), random.choice([YELLOW, WHITE, (255, 180, 80)]),
                                           random.randint(2, 6), grav=60, shape="circle"))

    def update_particles(self, dt):
        alive = []
        for p in self.particles:
            p.life -= dt
            if p.life <= 0:
                continue
            p.vy += p.grav * dt
            p.x += p.vx * dt
            p.y += p.vy * dt
            alive.append(p)
        self.particles = alive
        for t in self.texts:
            t.life -= dt
            t.y -= 40 * dt
        self.texts = [t for t in self.texts if t.life > 0]
        self.shake = max(0.0, self.shake - dt)

    # ---------------- drawing ----------------
    def blit(self, key, p, surf=None):
        (surf or self.screen).blit(self.img[key], self.px(p))

    def draw_level(self):
        lv, st, pg = self.level, self.state, self.pg
        now = time.time()
        red, green = lv.red_open(st.crates), lv.green_open(st.crates)
        up = spikes_up(st.moves)
        warn = lv.spikes and spike_phase(st.moves) == 1
        blink = (int(now * 6) % 2 == 0)
        # background layer (pits, switches, goals, spikes, portals)
        for y in range(lv.h):
            for x in range(lv.w):
                p = (x, y)
                if p in lv.walls:
                    self.blit("wall", p)
                    continue
                self.blit("floor", p)
                if p in lv.pits:
                    self.blit("pit_filled" if p in st.filled else "pit", p)
                elif p in lv.red_switches:
                    self.blit("red_switch", p)
                elif p in lv.green_switches:
                    self.blit("green_switch", p)
                elif p in lv.goals:
                    # pulsing glow behind the goal
                    glow = pg.Surface((T, T), pg.SRCALPHA)
                    a = int(60 + 50 * math.sin(now * 4))
                    pg.draw.rect(glow, (250, 220, 80, a), glow.get_rect(), border_radius=10)
                    self.screen.blit(glow, self.px(p))
                    self.blit("goal", p)
                elif p in lv.spikes:
                    if up:
                        self.blit("spike_up", p)
                    elif warn:
                        self.blit("spike_warn" if blink else "spike_down", p)
                    else:
                        self.blit("spike_down", p)
                elif p in lv.teleporters:
                    img = self.img["portal_" + lv.tele_id[p]]
                    ang = (now * 90) % 360
                    rot = pg.transform.rotate(img, ang)
                    r = rot.get_rect(center=self.center(p))
                    self.screen.blit(rot, r)
                elif p in lv.red_doors:
                    self.blit("red_door_open" if red else "red_door", p)
                elif p in lv.green_doors:
                    self.blit("green_door_open" if green else "green_door", p)
        # ghosts (crates falling into pits)
        keep = []
        for key, a, b, t0, dur in self.ghosts:
            t = (now - t0) * 1000 / dur
            if t < 1:
                x = lerp(self.px(a)[0], self.px(b)[0], t)
                y = lerp(self.px(a)[1], self.px(b)[1], t)
                self.screen.blit(self.img[key], (x, y))
                keep.append((key, a, b, t0, dur))
        self.ghosts = keep
        # crates
        for p, ct in st.crates.items():
            key = ct
            if ct == GREEN and not green:
                key = "green_inactive"
            x, y = self.px(p)
            if p in self.crate_anim:
                a, t0, dur = self.crate_anim[p]
                t = (now - t0) * 1000 / dur
                if t >= 1:
                    del self.crate_anim[p]
                else:
                    x = lerp(self.px(a)[0], x, t)
                    y = lerp(self.px(a)[1], y, t)
            self.screen.blit(self.img[key], (x, y))
        # hands
        for i, p in enumerate(st.hands):
            x, y = self.px(p)
            if i in self.hand_anim:
                a, t0 = self.hand_anim[i]
                t = (now - t0) * 1000 / ANIM_MS
                if t >= 1:
                    del self.hand_anim[i]
                else:
                    x = lerp(self.px(a)[0], x, t)
                    y = lerp(self.px(a)[1], y, t)
            bob = math.sin(now * 3 + i) * 2 if st.sprites[i] == "hand" else 0   # idle bounce
            self.screen.blit(self.img[st.sprites[i]], (x, y + bob))
        # particles
        for pt in self.particles:
            alpha = max(0, min(1, pt.life / pt.max_life))
            s = max(1, int(pt.size * (0.4 + 0.6 * alpha)))
            col = tuple(int(c * (0.5 + 0.5 * alpha)) for c in pt.color)
            if pt.shape == "circle":
                pg.draw.circle(self.screen, col, (int(pt.x), int(pt.y)), s)
            else:
                pg.draw.rect(self.screen, col, (int(pt.x), int(pt.y), s, s))
        for t in self.texts:
            surf = self.font.render(t.text, True, t.color)
            surf.set_alpha(int(255 * min(1, t.life / 0.4)))
            self.screen.blit(surf, surf.get_rect(center=(t.x, t.y)))

    def draw_hud(self):
        pg = self.pg
        pg.draw.rect(self.screen, HUD_BG, (0, 0, self.W, HUD_H))
        lv, st = self.level, self.state
        title = self.font.render(f"Level {self.level_index + 1}/{len(self.levels)}: {lv.name}", True, WHITE)
        self.screen.blit(title, (14, 10))
        moves = self.font.render(f"Moves: {st.moves}   Par: {lv.par}", True, YELLOW if st.moves <= lv.par else GREY)
        self.screen.blit(moves, (14, 34))
        star_txt = " ".join("*" * s for s in self.stars) if self.stars else ""
        total = self.small.render(f"Stars: {sum(self.stars)}", True, YELLOW)
        self.screen.blit(total, (self.W - 14 - total.get_width(), 10))
        keys = self.small.render("Arrows/WASD move   Z undo   R restart   Esc title", True, GREY)
        self.screen.blit(keys, (self.W - 14 - keys.get_width(), 36))
        hint = self.small.render(lv.hint, True, (190, 190, 205))
        self.screen.blit(hint, hint.get_rect(midtop=(self.W / 2, self.H - 30)))

    def draw_stars(self, n, cx, cy, size=40):
        pg = self.pg
        for k in range(3):
            x = cx + (k - 1) * (size + 14)
            col = YELLOW if k < n else (70, 70, 85)
            pts = []
            for j in range(10):
                r = size / 2 if j % 2 == 0 else size / 5
                a = -math.pi / 2 + j * math.pi / 5
                pts.append((x + math.cos(a) * r, cy + math.sin(a) * r))
            pg.draw.polygon(self.screen, col, pts)

    def overlay(self, alpha=170):
        s = self.pg.Surface((self.W, self.H), self.pg.SRCALPHA)
        s.fill((0, 0, 0, alpha))
        self.screen.blit(s, (0, 0))

    def text(self, font, txt, cx, cy, color=WHITE):
        s = font.render(txt, True, color)
        self.screen.blit(s, s.get_rect(center=(cx, cy)))

    def draw_title(self):
        now = time.time()
        self.screen.fill(BG)
        # animated background: drifting crates + hands
        random.seed(7)
        for k in range(14):
            sp = random.uniform(15, 40)
            x = (random.uniform(0, self.W) + now * sp) % (self.W + T) - T
            y = random.uniform(0, self.H)
            key = random.choice(["crate", "sliding", "green", "hand"])
            img = self.img[key].copy()
            img.set_alpha(60)
            self.screen.blit(img, (x, y + math.sin(now + k) * 8))
        random.seed()
        self.text(self.big, "HELPING HAND", self.W / 2, self.H * 0.28, YELLOW)
        self.text(self.font, "A push-the-crates puzzle", self.W / 2, self.H * 0.28 + 50, GREY)
        lines = [
            "Arrow keys / WASD: move every hand      Z: undo      R: restart level",
            "Push crates into pits to fill them.  Crates on switches open matching doors.",
            "Sliding crates keep going.  Green crates are ghosts until a green switch is pressed.",
            "Spikes rise every 2 moves.  Portals swap you (or a crate) to their twin.",
            "Fewer moves = more stars.  Every hand must reach a goal.",
        ]
        for i, l in enumerate(lines):
            self.text(self.small, l, self.W / 2, self.H * 0.52 + i * 24, (200, 200, 215))
        if int(now * 2) % 2 == 0:
            self.text(self.font, "Press ENTER to start", self.W / 2, self.H * 0.86, WHITE)

    def draw_results(self):
        self.screen.fill(BG)
        self.text(self.big, "YOU WIN!", self.W / 2, self.H * 0.2, YELLOW)
        total = sum(self.stars)
        self.text(self.font, f"Total stars: {total} / {3 * len(self.levels)}", self.W / 2, self.H * 0.32, WHITE)
        for i, s in enumerate(self.stars):
            y = self.H * 0.42 + i * 34
            self.text(self.small, f"{i + 1}. {self.levels[i].name}", self.W / 2 - 160, y, (200, 200, 215))
            self.draw_stars(s, self.W / 2 + 120, y, 22)
        self.text(self.font, "Press any key to return to the title", self.W / 2, self.H * 0.92, GREY)

    # ---------------- main loop ----------------
    def run(self):
        pg = self.pg
        running = True
        while running:
            dt = self.clock.tick(60) / 1000.0
            self.update_particles(dt)
            for ev in pg.event.get():
                if ev.type == pg.QUIT:
                    running = False
                elif ev.type == pg.KEYDOWN:
                    self.key(ev.key)
            if self.scene == "title":
                self.draw_title()
            elif self.scene == "results":
                self.draw_results()
            else:
                self.screen.fill(BG)
                self.draw_level()
                self.draw_hud()
                if self.shake > 0:
                    dx, dy = random.randint(-4, 4), random.randint(-4, 4)
                    self.screen.blit(self.screen.copy(), (dx, dy))
                if self.state.dead:
                    self.overlay(120)
                    self.text(self.big, "OUCH!", self.W / 2, self.H / 2 - 20, RED)
                    self.text(self.font, "Z to undo   R to restart", self.W / 2, self.H / 2 + 30, WHITE)
                elif self.scene == "clear":
                    self.overlay(150)
                    self.text(self.big, "LEVEL CLEAR", self.W / 2, self.H / 2 - 70, YELLOW)
                    self.draw_stars(self.earned, self.W / 2, self.H / 2)
                    self.text(self.font, f"{self.state.moves} moves  (par {self.level.par})", self.W / 2, self.H / 2 + 50, WHITE)
                    if time.time() - self.clear_time > 0.6:
                        self.text(self.small, "Press any key to continue", self.W / 2, self.H / 2 + 90, GREY)
            pg.display.flip()
        pg.quit()

    def key(self, k):
        pg = self.pg
        if self.scene == "title":
            if k in (pg.K_RETURN, pg.K_SPACE, pg.K_KP_ENTER):
                self.stars = []
                self.load_level(0)
            elif k == pg.K_ESCAPE:
                pg.event.post(pg.event.Event(pg.QUIT))
        elif self.scene == "results":
            self.scene = "title"
        elif self.scene == "clear":
            if time.time() - self.clear_time < 0.6:
                return
            self.stars.append(self.earned)
            if self.level_index + 1 < len(self.levels):
                self.load_level(self.level_index + 1)
            else:
                self.scene = "results"
        elif self.scene == "play":
            if k in (pg.K_LEFT, pg.K_a):
                self.try_move("left")
            elif k in (pg.K_RIGHT, pg.K_d):
                self.try_move("right")
            elif k in (pg.K_UP, pg.K_w):
                self.try_move("up")
            elif k in (pg.K_DOWN, pg.K_s):
                self.try_move("down")
            elif k == pg.K_z:
                self.undo()
            elif k == pg.K_r:
                self.load_level(self.level_index)
            elif k == pg.K_ESCAPE:
                self.scene = "title"
            elif k == pg.K_n and "--debug" in sys.argv:      # level skip, testing only
                self.stars.append(0)
                if self.level_index + 1 < len(self.levels):
                    self.load_level(self.level_index + 1)
                else:
                    self.scene = "results"


def main():
    try:
        import pygame  # noqa: F401
    except ImportError:
        print("pygame is not installed. Run:  python3 -m pip install pygame")
        sys.exit(1)
    Game().run()


if __name__ == "__main__":
    main()
