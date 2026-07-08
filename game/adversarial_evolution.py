"""
对抗演化 · 涌现  (Adversarial Evolution · Emergence)
A pygame sandbox where 8-trait agents co-evolve under selection pressure.
Strategies (夺利 / 合作 / 修身 / 好善疾恶 / 伪善) EMERGE from trait combinations
rather than being hardcoded. Player observes and lightly perturbs.

Book reference: 《对抗演化与合作跃升》 — repo/核心词汇表.md

Run:   python game/adversarial_evolution.py
Test:  SDL_VIDEODRIVER=dummy python game/adversarial_evolution.py --ticks 200
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import List, Tuple

import pygame

# ----------------------------------------------------------------------------
# Config
# ----------------------------------------------------------------------------

WORLD_W, WORLD_H = 960, 720
HUD_TOP_H = 168
HUD_BOTTOM_H = 56
PLAY_W, PLAY_H = WORLD_W, WORLD_H - HUD_TOP_H - HUD_BOTTOM_H
PLAY_OFFSET_Y = HUD_TOP_H

INIT_POP = 80
INIT_FOOD = 240
FOOD_TARGET = 140              # ABSOLUTE food target (not per-capita)
FOOD_SPAWN_PER_TICK = 3       # cap food supply so pop can't grow forever

# === Strategy classification (single source of truth) ===
# All HUD elements (strategy counts, stage label, good-rate, histograms)
# derive from classify_agent() and these shared thresholds. Do NOT introduce
# other classification thresholds elsewhere.
HIGH_THRESH = 0.6   # trait ≥ 此值 = "高" (e.g. high aggression → 夺利 / GVBE)
LOW_THRESH  = 0.4   # trait <  此值 = "低"
# AGENT_LABELS is the canonical list, in a stable display order
AGENT_LABELS = ("夺利", "互助合作", "好善疾恶", "修身", "未分化")

HISTORY_MAX = 2000             # HUD sparkline 保留多少 tick 的历史

# session logging
RUNS_DIR = Path(__file__).parent / "runs"

TRAIT_NAMES = (
    "aggression",
    "cooperation",
    "metabolism",
    "speed",
    "sense",
    "defense",
    "repro_thr",
    "mut_rate",
)
TRAIT_COUNT = len(TRAIT_NAMES)

# energy scale
MAX_ENERGY = 2.0
START_ENERGY = 0.8
SHARE_AMOUNT = 0.06
ATTACK_TRANSFER = 0.35
HUNGRY_THRESHOLD = 0.45
METAB_BASE = 0.004
METAB_SCALE = 0.015
REPRO_BASE = 1.1
REPRO_SCALE = 0.5

# visual
BG = (14, 14, 20)
GRID = (28, 28, 38)
FOOD_COLOR = (110, 220, 130)
HUD_FG = (220, 220, 230)
HUD_DIM = (140, 140, 160)


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------

def clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return lo if v < lo else hi if v > hi else v


def gauss(mu: float, sigma: float) -> float:
    return random.gauss(mu, sigma)


def trait_hue(t: dict) -> float:
    """Map (aggression, cooperation) position to hue [0,360].
    Lets the player SEE strategies emerge without labeling them.

    Cardinal corners map to intuitive colors:
        agg=1, coop=0  -> hue 0   (红, red)    -> 夺利
        agg=0, coop=1  -> hue 180 (青, cyan)   -> 互助合作 (cool family)
        agg=0, coop=0  -> hue 270 (蓝紫, violet) -> 修身
        agg=1, coop=1  -> hue 90  (黄绿, yellow-green) -> GVBE 好善疾恶
        near center    -> hue 60  (黄, yellow)  -> 未分化

    Note: due to trait-space being a 90°-cornered square while target hues
    are 60°/120° apart, no single linear rotation hits all 4 corners exactly.
    This formula prioritizes 夺利=red (the most visually important distinction).
    """
    dx = t["aggression"] - 0.5
    dy = t["cooperation"] - 0.5
    # center special-case: very close to (0.5, 0.5) -> yellow (未分化)
    if abs(dx) < 0.04 and abs(dy) < 0.04:
        return 60.0
    # atan2(dx+dy, dx-dy) rotates trait space 45° and maps:
    #   (1,0) -> (0.5, 0.5) → atan2(0.5,0.5) = 0°   ✓ red
    #   (0,1) -> (-0.5,-0.5) → atan2(-0.5,-0.5) = 180° cyan
    #   (0,0) -> (-0.5, 0.5) → atan2(-0.5,0.5) = 270° purple ✓
    #   (1,1) -> (0.5, -0.5) → atan2(0.5,-0.5) = 90°  yellow-green
    return (math.degrees(math.atan2(dx + dy, dx - dy)) + 360.0) % 360.0


def classify_agent(t: dict) -> str:
    """Per-agent strategy label based on (aggression, cooperation) position.

    SINGLE SOURCE OF TRUTH for what each agent "is". All other UI elements
    (strategy counts, stage classifier, good-rate, histograms) derive from
    this function and the shared HIGH_THRESH / LOW_THRESH constants.

    Trait space is divided into 4 corner quadrants + 1 catch-all center:

        coop
         1 ┌────────────┬────────────┐
           │ 互助合作   │  好善疾恶  │
           │ (high coop │ (high agg  │
           │  low agg)  │  high coop)│
       0.6├────────────┼────────────┤ ← HIGH_THRESH
           │            │            │
       0.4├────────────┼────────────┤ ← LOW_THRESH
           │  修身      │   夺利    │
           │ (low both) │ (high agg │
           │            │  low coop) │
         0 └────────────┴────────────┘
         0    0.4    0.6    1     agg
    """
    agg = t["aggression"]
    coop = t["cooperation"]
    high_agg = agg >= HIGH_THRESH
    low_agg = agg < LOW_THRESH
    high_coop = coop >= HIGH_THRESH
    low_coop = coop < LOW_THRESH
    if high_agg and low_coop:
        return "夺利"
    if high_coop and low_agg:
        return "互助合作"
    if high_agg and high_coop:
        return "好善疾恶"
    if low_agg and low_coop:
        return "修身"
    return "未分化"


def _hue_for_label(label: str) -> float:
    """Return the representative hue for a strategy label.

    Reverse of classify_agent: given a label, return the hue that agents
    of this label are rendered with in the world. Uses trait_hue on a
    canonical mid-trait position so the HUD bar color matches the dots.
    """
    samples = {
        "夺利":     (0.8, 0.2),    # agg 0.8, coop 0.2
        "互助合作":  (0.2, 0.8),
        "好善疾恶":  (0.8, 0.8),
        "修身":     (0.2, 0.2),
        "未分化":   (0.5, 0.5),
    }
    a, c = samples[label]
    return trait_hue({"aggression": a, "cooperation": c})


def _label_color(label: str, light: float = 0.55, sat: float = 0.75) -> tuple:
    """RGB color for a strategy label, with 未分化 rendered as gray.

    Gray makes the "未分化" catch-all visually distinct from the 4 vivid
    corner strategies (which sit at 90° hue intervals). Sat=0 collapses
    the color to neutral gray regardless of hue.
    """
    if label == "未分化":
        return _hls_to_rgb(0.0, light, 0.0)   # gray
    hue = _hue_for_label(label)
    return _hls_to_rgb(hue / 360.0, light, sat)


# Backward-compat alias — old HUD code called it strategy_label
strategy_label = classify_agent


# ----------------------------------------------------------------------------
# Agent
# ----------------------------------------------------------------------------

@dataclass
class Agent:
    x: float
    y: float
    energy: float
    age: int = 0
    generation: int = 0
    traits: dict = field(default_factory=dict)

    @staticmethod
    def random_traits() -> dict:
        return {n: random.random() for n in TRAIT_NAMES}

    @classmethod
    def spawn(cls, x: float, y: float, traits: dict | None = None, gen: int = 0) -> "Agent":
        return cls(
            x=x, y=y,
            energy=START_ENERGY,
            traits=traits if traits is not None else cls.random_traits(),
            generation=gen,
        )

    def mutate_child(self) -> "Agent":
        sigma = max(0.02, self.traits["mut_rate"] * 0.25)
        child_traits = {n: clamp(self.traits[n] + gauss(0.0, sigma)) for n in TRAIT_NAMES}
        # half energy, parent loses the other half (with small efficiency loss)
        split = self.energy * 0.5
        self.energy -= split
        return Agent(
            x=self.x + random.uniform(-4, 4),
            y=self.y + random.uniform(-4, 4),
            energy=split,
            traits=child_traits,
            generation=self.generation + 1,
        )


# ----------------------------------------------------------------------------
# World
# ----------------------------------------------------------------------------

class World:
    AUTOSAVE_INTERVAL = 500  # ticks between autosaves (overwritten in-place)

    def __init__(self, w: int = PLAY_W, h: int = PLAY_H) -> None:
        self.w = w
        self.h = h
        self.agents: List[Agent] = []
        self.food: List[Tuple[float, float, float]] = []  # (x, y, amount)
        self.tick = 0
        self.births = 0
        self.deaths = 0
        # run identity — used as autosave filename so each new run gets its own
        self.run_id = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        self.autosave_path: Path = RUNS_DIR / f"autosave_{self.run_id}.json"
        self._last_autosave_tick = 0
        # per-tick metric history (ring buffer of length HISTORY_MAX)
        self.good_hist: List[float] = []     # 善者率: (互助合作+好善疾恶) / pop
        self.coop_only_hist: List[float] = []  # 合作者率: 互助合作 / pop
        self.pop_hist: List[int] = []
        self.agg_hist: List[float] = []
        self.coop_hist: List[float] = []
        # per-strategy-category fraction over time (5 lines for the HUD chart)
        self.cat_hist: Dict[str, List[float]] = {
            label: [] for label in AGENT_LABELS
        }
        # stage transitions for the run log
        self.stage_transitions: List[dict] = []
        self._last_stage: str = ""
        self._spawn_initial()

    # -- spawning ----------------------------------------------------------
    def _spawn_initial(self) -> None:
        for _ in range(INIT_POP):
            self.agents.append(Agent.spawn(
                random.uniform(0, self.w), random.uniform(0, self.h)
            ))
        for _ in range(INIT_FOOD):
            self.food.append((
                random.uniform(0, self.w),
                random.uniform(0, self.h),
                random.uniform(0.25, 0.5),
            ))

    def spawn_food(self, n: int) -> None:
        for _ in range(n):
            self.food.append((
                random.uniform(0, self.w),
                random.uniform(0, self.h),
                random.uniform(0.25, 0.55),
            ))

    def inject_agent(self, x: float, y: float) -> None:
        self.agents.append(Agent.spawn(x, y))

    def inject_food(self, x: float, y: float) -> None:
        self.food.append((x, y, 0.6))

    # -- geometry helpers --------------------------------------------------
    def wrap(self, x: float, y: float) -> Tuple[float, float]:
        return x % self.w, y % self.h

    def neighbors(self, a: Agent, radius: float) -> List[Agent]:
        r2 = radius * radius
        out: List[Agent] = []
        for other in self.agents:
            if other is a:
                continue
            dx = other.x - a.x
            dy = other.y - a.y
            # toroidal shortest distance
            if dx > self.w / 2: dx -= self.w
            if dx < -self.w / 2: dx += self.w
            if dy > self.h / 2: dy -= self.h
            if dy < -self.h / 2: dy += self.h
            if dx * dx + dy * dy <= r2:
                out.append(other)
        return out

    # -- main step ---------------------------------------------------------
    def step(self) -> None:
        self.tick += 1

        # 1. each agent acts
        random.shuffle(self.agents)
        newborns: List[Agent] = []

        for a in self.agents:
            self._agent_act(a, newborns)

        # 2. integrate newborns
        if newborns:
            self.agents.extend(newborns)
            self.births += len(newborns)

        # 3. remove dead
        survivors: List[Agent] = []
        for a in self.agents:
            if a.energy > 0.0:
                a.age += 1
                survivors.append(a)
            else:
                self.deaths += 1
        self.agents = survivors

        # 4. maintain food pressure (density-independent)
        if len(self.food) < FOOD_TARGET:
            self.spawn_food(FOOD_SPAWN_PER_TICK)

        # 5. record metrics history for HUD stage classifier + sparkline
        self._record_metrics()

        # 6. autosave every AUTOSAVE_INTERVAL ticks (overwrites previous autosave)
        if self.tick - self._last_autosave_tick >= self.AUTOSAVE_INTERVAL:
            p = save_run(self, "autosave", path=self.autosave_path)
            self._last_autosave_tick = self.tick
            if p and os.environ.get("DEBUG_TELEMETRY") == "1":
                sys.stderr.write(f"[autosave] {p}\n")
                sys.stderr.flush()

        # periodic telemetry (DEBUG_TELEMETRY=1)
        if os.environ.get("DEBUG_TELEMETRY") == "1" and self.tick % 50 == 0:
            if self.agents:
                avg_e = sum(a.energy for a in self.agents) / len(self.agents)
                avg_a = sum(a.traits["aggression"] for a in self.agents) / len(self.agents)
                avg_c = sum(a.traits["cooperation"] for a in self.agents) / len(self.agents)
            else:
                avg_e = avg_a = avg_c = 0.0
            print(f"t={self.tick:>4} pop={len(self.agents):>3} "
                  f"food={len(self.food):>3} births={self.births} "
                  f"deaths={self.deaths} avgE={avg_e:.2f} "
                  f"avgAgg={avg_a:.2f} avgCoop={avg_c:.2f} "
                  f"good={self.good_rate():.2f} stage={self.current_stage()}")

    def _agent_act(self, a: Agent, newborns: List[Agent]) -> None:
        t = a.traits

        # pay metabolism (scaled)
        a.energy -= METAB_BASE + METAB_SCALE * t["metabolism"]

        # sense neighbors
        sense_r = 18 + 80 * t["sense"]
        ns = self.neighbors(a, sense_r)

        # ----- adversarial interactions -----
        if a.energy < HUNGRY_THRESHOLD and ns and random.random() < t["aggression"]:
            # attack weakest neighbor with strictly less energy (otherwise risky)
            target = min(ns, key=lambda o: o.energy + random.random() * 0.05)
            if target.energy < a.energy * 1.4:
                defense = target.traits["defense"]
                taken = ATTACK_TRANSFER * (1.0 - 0.6 * defense)
                # attacker pays an aggression tax (book: 夺利亏损定律)
                a.energy = min(MAX_ENERGY, a.energy + taken - 0.06)
                target.energy -= taken

        if ns and random.random() < t["cooperation"] * 0.6:
            # share with nearest same-hue neighbor (合作红利: 1+1>2)
            my_hue = trait_hue(t)
            same = [o for o in ns if abs(trait_hue(o.traits) - my_hue) < 35.0]
            if same:
                partner = min(same,
                              key=lambda o: (o.x - a.x) ** 2 + (o.y - a.y) ** 2)
                if a.energy > 0.5 and partner.energy < 0.7:
                    a.energy -= SHARE_AMOUNT
                    partner.energy = min(MAX_ENERGY, partner.energy + SHARE_AMOUNT)

        # ----- movement -----
        speed = 1 + 6 * t["speed"]
        # bias toward nearest food when not yet well-fed
        bias_x, bias_y = 0.0, 0.0
        if a.energy < REPRO_BASE + REPRO_SCALE * 0.4 and self.food:
            best = None
            best_d2 = 1e18
            for fx, fy, _ in self.food:
                dx = fx - a.x
                dy = fy - a.y
                d2 = dx * dx + dy * dy
                if d2 < best_d2:
                    best_d2 = d2
                    best = (fx, fy)
            if best is not None:
                ddx = best[0] - a.x
                ddy = best[1] - a.y
                mag = math.sqrt(ddx * ddx + ddy * ddy) + 1e-6
                bias_x = ddx / mag
                bias_y = ddy / mag
        # blend random walk + bias
        rnd_x = random.uniform(-1, 1)
        rnd_y = random.uniform(-1, 1)
        bx = 0.6 * rnd_x + 0.4 * bias_x
        by = 0.6 * rnd_y + 0.4 * bias_y
        a.x = (a.x + bx * speed) % self.w
        a.y = (a.y + by * speed) % self.h

        # ----- eat -----
        remaining: List[Tuple[float, float, float]] = []
        ate = False
        eat_r = 8
        for fx, fy, fam in self.food:
            if not ate and abs(fx - a.x) < eat_r and abs(fy - a.y) < eat_r:
                a.energy = min(MAX_ENERGY, a.energy + fam)
                ate = True
            else:
                remaining.append((fx, fy, fam))
        self.food = remaining

        # ----- reproduce -----
        repro_need = REPRO_BASE + REPRO_SCALE * t["repro_thr"]
        if a.energy > repro_need and random.random() < 0.05:
            newborns.append(a.mutate_child())

    # -- metrics & stage classification ------------------------------------
    def _strategy_counts(self) -> dict:
        """Count agents per AGENT_LABELS using classify_agent.
        This is the canonical population distribution used by all UI."""
        from collections import Counter
        c = Counter(classify_agent(a.traits) for a in self.agents)
        return {label: c.get(label, 0) for label in AGENT_LABELS}

    def good_rate(self) -> float:
        """Fraction of agents that are 互助合作 OR 好善疾恶 (i.e. high-coop).
        Derived from classify_agent — matches the '善者' definition exactly.
        """
        if not self.agents:
            return 0.0
        counts = self._strategy_counts()
        good = counts["互助合作"] + counts["好善疾恶"]
        return good / len(self.agents)

    def coop_only_rate(self) -> float:
        """Fraction of agents that are pure 互助合作 (cooperators only,
        excluding 好善疾恶 'judges'). Distinguishes passive cooperator
        share from the broader 善者 pool.
        """
        if not self.agents:
            return 0.0
        counts = self._strategy_counts()
        return counts["互助合作"] / len(self.agents)

    def _avg_trait(self, name: str) -> float:
        if not self.agents:
            return 0.0
        return sum(a.traits[name] for a in self.agents) / len(self.agents)

    def _record_metrics(self) -> None:
        self.good_hist.append(self.good_rate())
        self.coop_only_hist.append(self.coop_only_rate())
        self.pop_hist.append(len(self.agents))
        self.agg_hist.append(self._avg_trait("aggression"))
        self.coop_hist.append(self._avg_trait("cooperation"))
        # per-category fractions
        counts = self._strategy_counts()
        pop = max(1, len(self.agents))
        for label in AGENT_LABELS:
            self.cat_hist[label].append(counts[label] / pop)
        # trim to ring buffer length
        all_hist = (self.good_hist, self.coop_only_hist, self.pop_hist,
                    self.agg_hist, self.coop_hist,
                    *[self.cat_hist[l] for l in AGENT_LABELS])
        for h in all_hist:
            if len(h) > HISTORY_MAX:
                del h[: len(h) - HISTORY_MAX]
        # track stage transitions (only when stage actually changes)
        stage = self.current_stage()
        if stage != self._last_stage:
            self.stage_transitions.append({"tick": self.tick, "stage": stage})
            self._last_stage = stage

    def current_stage(self) -> str:
        """Population-level label derived entirely from classify_agent counts.

        Strategy counts are first computed by classify_agent; stage rules are
        pure fractions (p_X = counts[X] / pop). No raw avgAgg/avgCoop here —
        those thresholds are decoupled to avoid inconsistent classification.
        """
        if not self.agents:
            return "空"
        if self.tick < 60:
            return "起始混乱"

        pop = len(self.agents)
        c = self._strategy_counts()
        p_grab = c["夺利"] / pop
        p_coop = c["互助合作"] / pop
        p_gvbe = c["好善疾恶"] / pop
        p_self = c["修身"] / pop
        p_high_coop = p_coop + p_gvbe   # 互助合作 ∪ 好善疾恶 = 善者

        # pop trend over last ~60 ticks
        window = self.pop_hist[-60:] if len(self.pop_hist) >= 60 else self.pop_hist[:]
        pop_delta = (window[-1] - window[0]) if len(window) >= 2 else 0
        pop_delta_abs = abs(pop_delta)

        # Priority order — first matching rule wins
        if pop < 25:
            return "濒临灭绝"
        if p_grab >= 0.60:
            return "霍布斯丛林"
        if p_high_coop >= 0.50 and pop >= 100:
            if pop_delta_abs < 20:
                return "伊甸园期"
            return "合作繁荣中"
        if p_self >= 0.50:
            return "修身主导"
        if p_gvbe >= 0.30:
            return "好善疾恶主导"
        if p_grab >= 0.40:
            return "夺利丛林"
        if pop_delta < -40:
            return "维度坍缩中"
        if pop_delta > 25:
            return "增长中"
        return "未分化"


# ----------------------------------------------------------------------------
# Rendering
# ----------------------------------------------------------------------------

class Renderer:
    def __init__(self, screen: pygame.Surface) -> None:
        self.screen = screen
        self.font = self._safe_font(14)
        self.font_big = self._safe_font(18, bold=True)
        self.font_lbl = self._safe_font(11)
        self.step_errors = 0

    @staticmethod
    def _safe_font(size: int, bold: bool = False) -> pygame.font.Font:
        """Find a font that can render Chinese. Tries:
        1. Direct file paths (most reliable on Windows for CJK glyphs)
        2. SysFont with CJK family names
        3. Pygame default (will show ??? for CJK but won't crash)
        """
        # 1. Try explicit CJK font files
        cjk_paths = [
            r"C:\Windows\Fonts\msyh.ttc",   # Microsoft YaHei UI
            r"C:\Windows\Fonts\msyh.ttf",
            r"C:\Windows\Fonts\simhei.ttf", # SimHei (黑体)
            r"C:\Windows\Fonts\simsun.ttc", # SimSun (宋体)
            r"C:\Windows\Fonts\Deng.ttf",   # DengXian (等线)
            r"C:\Windows\Fonts\msyhbd.ttc", # YaHei bold
            "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
            "/System/Library/Fonts/PingFang.ttc",
        ]
        for path in cjk_paths:
            if os.path.exists(path):
                try:
                    f = pygame.font.Font(path, size)
                    if bold:
                        f.set_bold(True)
                    return f
                except Exception:
                    continue
        # 2. Try SysFont with CJK family names
        for name in ("microsoftyaheiui", "microsoftyahei", "simhei",
                     "dengxian", "simsun", "nsimsun", "notosanscjksc",
                     "pingfang", "stheiti", "wenquanyimicrohei"):
            f = pygame.font.SysFont(name, size, bold=bold)
            if f is not None:
                # default font renders CJK as ~1px-wide blank; real CJK font returns real width
                if f.render("测", True, (0, 0, 0)).get_width() > 2:
                    return f
        # 3. Last resort
        return pygame.font.Font(None, size)

    def draw(self, world: World, paused: bool, mode: str, speed: float,
             frame: int = 0) -> None:
        self.screen.fill(BG)
        self._draw_grid(world)
        self._draw_food(world)
        self._draw_agents(world)
        self._draw_hud(world, paused, mode, speed, frame)

    def _draw_grid(self, world: World) -> None:
        step = 60
        for x in range(0, world.w, step):
            pygame.draw.line(self.screen, GRID, (x, PLAY_OFFSET_Y), (x, PLAY_OFFSET_Y + PLAY_H), 1)
        for y in range(0, world.h, step):
            pygame.draw.line(self.screen, GRID, (0, PLAY_OFFSET_Y + y), (world.w, PLAY_OFFSET_Y + y), 1)

    def _draw_food(self, world: World) -> None:
        for fx, fy, fam in world.food:
            r = 2 + int(2 * fam)
            pygame.draw.circle(self.screen, FOOD_COLOR,
                               (int(fx), int(fy) + PLAY_OFFSET_Y), r)

    def _draw_agents(self, world: World) -> None:
        for a in world.agents:
            light = 0.45 + 0.25 * (a.energy / MAX_ENERGY)
            # center agents (未分化) are gray so they don't blur with 好善疾恶 (yellow-green)
            dx = abs(a.traits["aggression"] - 0.5)
            dy = abs(a.traits["cooperation"] - 0.5)
            if dx < 0.04 and dy < 0.04:
                color = _hls_to_rgb(0.0, light, 0.0)  # gray
            else:
                hue = trait_hue(a.traits)
                sat = 0.55 + 0.35 * (1.0 - abs(a.traits["aggression"] - a.traits["cooperation"]))
                color = _hls_to_rgb(hue / 360.0, light, sat)
            r = 3 + int(6 * (a.energy / MAX_ENERGY))
            pygame.draw.circle(
                self.screen,
                color,
                (int(a.x), int(a.y) + PLAY_OFFSET_Y),
                r,
            )

    def _draw_hud(self, world: World, paused: bool, mode: str, speed: float,
                   frame: int = 0) -> None:
        # top bar
        pygame.draw.rect(self.screen, (20, 20, 28),
                         (0, 0, WORLD_W, HUD_TOP_H))
        title = self.font_big.render("对抗演化 · 涌现", True, HUD_FG)
        self.screen.blit(title, (12, 8))

        stats = (
            f"tick {world.tick:>6}   "
            f"gen {max((a.generation for a in world.agents), default=0):>3}   "
            f"pop {len(world.agents):>3}   "
            f"food {len(world.food):>3}   "
            f"births {world.births}  deaths {world.deaths}   "
            f"{'PAUSED' if paused else 'running'}  x{speed:.1f}  "
            f"mode={mode}"
        )
        self.screen.blit(self.font.render(stats, True, HUD_FG), (12, 36))

        # strategy counts — show ALL 5 categories in fixed AGENT_LABELS order
        # (so 0-count categories are visible, not hidden as "top 3")
        if world.agents:
            counts = world._strategy_counts()
            txt = "  ".join(f"{label} {counts[label]}" for label in AGENT_LABELS)
            self.screen.blit(self.font.render("策略占比 " + txt, True, HUD_FG),
                             (12, 60))

        # ===== STAGE LABEL + 善者率 SPARKLINE =====
        stage = world.current_stage()
        good = world.good_rate()
        # color stage label based on category
        if "霍布斯" in stage or "坍缩" in stage or "灭绝" in stage:
            stage_color = (255, 110, 110)   # red
        elif "伊甸园" in stage or "繁荣" in stage or "朴素合作" in stage:
            stage_color = (110, 220, 150)   # green
        elif "夺利" in stage or "丛林" in stage:
            stage_color = (240, 170, 90)    # orange
        else:
            stage_color = HUD_FG
        self.screen.blit(self.font_big.render(f"阶段：{stage}", True, stage_color),
                         (12, 84))
        coop_only = world.coop_only_rate()
        self.screen.blit(self.font.render(
            f"善者率（{AGENT_LABELS[1]}+{AGENT_LABELS[2]}）：{good*100:5.1f}%",
            True, HUD_DIM), (12, 110))
        self.screen.blit(self.font.render(
            f"合作者率（{AGENT_LABELS[1]}）：{coop_only*100:5.1f}%",
            True, HUD_DIM), (12, 126))

        # 5-line strategy time series (right side, below the strategy bars)
        sp_x = WORLD_W - 230
        sp_y = 82
        sp_w = 220
        sp_h = 56
        # background
        pygame.draw.rect(self.screen, (28, 28, 38),
                         (sp_x, sp_y, sp_w, sp_h))
        # 0.5 reference line
        pygame.draw.line(self.screen, (50, 50, 60),
                         (sp_x, sp_y + sp_h // 2),
                         (sp_x + sp_w, sp_y + sp_h // 2), 1)
        # 5 lines, one per AGENT_LABELS, colored with strategy hue
        for label in AGENT_LABELS:
            hist = world.cat_hist[label]
            if len(hist) < 2:
                continue
            color = _label_color(label, light=0.55, sat=0.85)
            pts = []
            for i, v in enumerate(hist):
                px = sp_x + int(i * sp_w / HISTORY_MAX)
                py = sp_y + sp_h - int(v * sp_h)
                pts.append((px, py))
            pygame.draw.lines(self.screen, color, False, pts, 1)
        # legend (5 labels in fixed slots above the chart; use actual text width)
        legend_y = sp_y - 12
        slot_w = sp_w // len(AGENT_LABELS)
        for i, label in enumerate(AGENT_LABELS):
            color = _label_color(label, light=0.55, sat=0.85)
            txt_surf = self.font_lbl.render(label, True, color)
            cx = sp_x + i * slot_w + slot_w // 2
            self.screen.blit(txt_surf, (cx - txt_surf.get_width() // 2, legend_y))

        # 策略分布条形图（右上角，替换旧的 1D 直方图）
        # 5 行 = 5 个 AGENT_LABELS, 颜色 = 该策略的 hue (跟世界圆点同色系)
        if world.agents:
            self._strategy_bars(world, sp_x, y=4, w=sp_w)

            # frame counter + autosave indicator
            self.screen.blit(self.font_lbl.render(
                f"frame {frame}  step-err {self.step_errors}",
                True, HUD_DIM), (sp_x, 150))
            autosave_age = world.tick - world._last_autosave_tick
            autosave_str = f"autosave @t{world._last_autosave_tick} (-{autosave_age})"
            self.screen.blit(self.font_lbl.render(
                autosave_str, True, HUD_DIM), (sp_x, 160))

        # bottom bar
        pygame.draw.rect(self.screen, (20, 20, 28),
                         (0, WORLD_H - HUD_BOTTOM_H, WORLD_W, HUD_BOTTOM_H))
        help_txt = ("SPACE pause · R reset · N inject agent · F drop food · "
                    "+/- speed · ESC quit   |   click in play area to apply current mode")
        self.screen.blit(self.font.render(help_txt, True, HUD_DIM),
                         (12, WORLD_H - HUD_BOTTOM_H + 18))

    def _strategy_bars(self, world: World, x: int, y: int, w: int) -> None:
        """5-row horizontal bar chart showing the strategy distribution.

        Each row = one AGENT_LABELS entry. Bar color = that strategy's hue
        (matches the world dots via _hue_for_label). Bar length = count.
        Zero-count strategies get a thin grey track so they remain visible.

        Layout per row: [label 50px] [bar up to 140px] [count 25px]
        """
        counts = world._strategy_counts()
        max_c = max(counts.values()) or 1
        label_w = 50
        count_w = 25
        bar_w_max = max(20, w - label_w - count_w)
        row_h = 13
        track_color = (45, 45, 60)   # background track for zero-count rows

        for i, label in enumerate(AGENT_LABELS):
            row_y = y + i * row_h
            c = counts[label]
            # label
            self.screen.blit(self.font_lbl.render(label, True, HUD_FG),
                             (x, row_y + 1))
            # background track (always drawn, even if count is 0)
            bar_x = x + label_w
            pygame.draw.rect(self.screen, track_color,
                             (bar_x, row_y + 3, bar_w_max, 8))
            # colored bar (未分化 = gray via _label_color)
            if c > 0:
                color = _label_color(label, light=0.55, sat=0.75)
                bw = max(2, int(bar_w_max * c / max_c))
                pygame.draw.rect(self.screen, color,
                                 (bar_x, row_y + 3, bw, 8))
            # count
            self.screen.blit(
                self.font_lbl.render(str(c), True, HUD_DIM),
                (x + label_w + bar_w_max + 4, row_y + 1),
            )


def _hls_to_rgb(h: float, l: float, s: float) -> Tuple[int, int, int]:
    """Lightweight HLS -> RGB (avoid importing colorsys for perf)."""
    def f(n):
        k = (n + h * 12.0) % 12.0
        a = s * min(l, 1 - l)
        return l - a * max(-1.0, min(k - 3.0, 9.0 - k, 1.0))
    r, g, b = f(0), f(8), f(4)
    return int(r * 255), int(g * 255), int(b * 255)


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------

def save_run(world: World, ended_reason: str, path: Path | None = None) -> Path | None:
    """Dump the current world state + per-tick metrics history to a JSON file
    under runs/. If `path` is given (autosave), write there; else use a
    timestamped filename. Returns the saved path, or None on failure."""
    try:
        RUNS_DIR.mkdir(exist_ok=True)
        if path is None:
            ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            path = RUNS_DIR / f"{ts}.json"
        else:
            ts = path.stem.replace("autosave_", "")  # for payload
        # build time-series (downsampled if too long, but keep all transitions)
        n = len(world.pop_hist)
        history = [
            {
                "tick": i,
                "pop": world.pop_hist[i],
                "agg": round(world.agg_hist[i], 4),
                "coop": round(world.coop_hist[i], 4),
                "good": round(world.good_hist[i], 4),
                "coopOnly": round(world.coop_only_hist[i], 4),
                "cat": {label: round(world.cat_hist[label][i], 4)
                        for label in AGENT_LABELS},
            }
            for i in range(n)
        ]
        payload = {
            "timestamp": ts,
            "ended_reason": ended_reason,
            "ticks": world.tick,
            "births": world.births,
            "deaths": world.deaths,
            "final": {
                "pop": len(world.agents),
                "avgAgg": round(world._avg_trait("aggression"), 4),
                "avgCoop": round(world._avg_trait("cooperation"), 4),
                "goodRate": round(world.good_rate(), 4),
                "coopOnlyRate": round(world.coop_only_rate(), 4),
                "stage": world.current_stage(),
                "maxGen": max((a.generation for a in world.agents), default=0),
                "food": len(world.food),
            },
            "stage_transitions": list(world.stage_transitions),
            "history": history,
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                        encoding="utf-8")
        return path
    except Exception as e:
        sys.stderr.write(f"[save_run] failed: {e}\n")
        sys.stderr.flush()
        return None


def run_headless(ticks: int, seed: int | None) -> dict:
    pygame.init()
    pygame.display.set_mode((WORLD_W, WORLD_H))
    if seed is not None:
        random.seed(seed)
    world = World()
    for _ in range(ticks):
        world.step()
    return {
        "ticks": world.tick,
        "pop": len(world.agents),
        "food": len(world.food),
        "births": world.births,
        "deaths": world.deaths,
        "max_gen": max((a.generation for a in world.agents), default=0),
    }


def run_interactive() -> int:
    import traceback
    try:
        sys.stderr.write("[boot] pygame.init...\n"); sys.stderr.flush()
        pygame.init()
        if not pygame.font.get_init():
            pygame.font.init()
        sys.stderr.write(f"[boot] pygame {pygame.version.ver}, display OK\n"); sys.stderr.flush()
        screen = pygame.display.set_mode((WORLD_W, WORLD_H))
        pygame.display.set_caption("对抗演化 · 涌现")
        clock = pygame.time.Clock()
        renderer = Renderer(screen)
        sys.stderr.write("[boot] building world...\n"); sys.stderr.flush()
        world = World()
        sys.stderr.write(f"[boot] world ready: {len(world.agents)} agents, {len(world.food)} food\n"); sys.stderr.flush()

        paused = False
        speed = 1.0
        mode = "agent"  # 'agent' or 'food'
        frame = 0

        while True:
            try:
                for event in pygame.event.get():
                    if event.type == pygame.QUIT:
                        path = save_run(world, "window-close")
                        if path:
                            sys.stderr.write(f"[saved] {path}\n")
                            sys.stderr.flush()
                        return 0
                    if event.type == pygame.KEYDOWN:
                        if event.key == pygame.K_ESCAPE:
                            path = save_run(world, "ESC")
                            if path:
                                sys.stderr.write(f"[saved] {path}\n")
                                sys.stderr.flush()
                            return 0
                        if event.key == pygame.K_SPACE:
                            paused = not paused
                        elif event.key == pygame.K_r:
                            path = save_run(world, "reset")
                            if path:
                                sys.stderr.write(f"[saved] {path}\n")
                                sys.stderr.flush()
                            world = World()
                        elif event.key == pygame.K_n:
                            mode = "agent"
                        elif event.key == pygame.K_f:
                            mode = "food"
                        elif event.key in (pygame.K_PLUS, pygame.K_EQUALS):
                            speed = min(8.0, speed + 0.5)
                        elif event.key in (pygame.K_MINUS, pygame.K_UNDERSCORE):
                            speed = max(0.05, speed - 0.5)
                    if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                        mx, my = event.pos
                        if PLAY_OFFSET_Y <= my < PLAY_OFFSET_Y + PLAY_H:
                            wx, wy = mx, my - PLAY_OFFSET_Y
                            if mode == "agent":
                                world.inject_agent(wx, wy)
                            else:
                                world.inject_food(wx, wy)

                if not paused:
                    steps = max(1, int(round(speed)))
                    for _ in range(steps):
                        world.step()

                renderer.draw(world, paused, mode, speed, frame)
                pygame.display.flip()
                clock.tick(60)
                frame += 1
            except Exception as inner_e:
                # per-frame catch so a single bad tick can't kill the whole loop
                renderer.step_errors += 1
                if renderer.step_errors <= 3:
                    tb = traceback.format_exc()
                    sys.stderr.write(f"[frame {frame}] {tb}\n")
                    sys.stderr.flush()
                if renderer.step_errors > 100:
                    raise inner_e
                # brief yield so the window doesn't look frozen
                pygame.time.wait(50)
    except Exception as e:
        # log crash to file so user can inspect even after window closes
        tb = traceback.format_exc()
        log_path = os.path.join(os.path.dirname(__file__), "crash.log")
        try:
            with open(log_path, "w", encoding="utf-8") as f:
                f.write(tb)
        except Exception:
            pass
        # also save whatever run state we have so post-mortem is possible
        try:
            path = save_run(world, "crash")
            if path:
                sys.stderr.write(f"[saved on crash] {path}\n")
                sys.stderr.flush()
        except Exception:
            pass
        sys.stderr.write(tb)
        sys.stderr.flush()
        try:
            input("\n[crash] 程序已退出。栈跟踪已写入 crash.log。按回车关闭窗口...\n")
        except EOFError:
            pass
        return 1


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description="Adversarial evolution sandbox")
    p.add_argument("--ticks", type=int, default=0,
                   help="if >0, run headless for N ticks then exit")
    p.add_argument("--seed", type=int, default=None)
    args = p.parse_args(argv)

    if args.ticks > 0:
        stats = run_headless(args.ticks, args.seed)
        for k, v in stats.items():
            print(f"{k}: {v}")
        return 0
    return run_interactive()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))