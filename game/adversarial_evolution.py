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
HUD_TOP_H = 128
HUD_BOTTOM_H = 56
PLAY_W, PLAY_H = WORLD_W, WORLD_H - HUD_TOP_H - HUD_BOTTOM_H
PLAY_OFFSET_Y = HUD_TOP_H

INIT_POP = 80
INIT_FOOD = 240
FOOD_TARGET = 140              # ABSOLUTE food target (not per-capita)
FOOD_SPAWN_PER_TICK = 3       # cap food supply so pop can't grow forever

# "善者" 定义：cooperation 性状高于此阈值视为好善疾恶倾向
GOOD_COOP_THRESHOLD = 0.5
HISTORY_MAX = 220              # HUD sparkline 保留多少 tick 的历史

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
        hue 0   (red)    = high agg, low coop     -> 夺利-ish
        hue 120 (green)  = high coop, low agg     -> 合作-ish
        hue 300 (purple) = low both               -> 修身-ish
    """
    dx = t["aggression"] - 0.5
    dy = t["cooperation"] - 0.5
    # atan2 returns [-pi, pi]; shift so (dx=+, dy=0) -> 0 (red)
    return (math.degrees(math.atan2(dx, dy)) + 360.0) % 360.0


def strategy_label(t: dict) -> str:
    """Soft heuristic label for HUD only. Game logic does not use this."""
    agg, coop, met = t["aggression"], t["cooperation"], t["metabolism"]
    if agg > 0.62 and coop < 0.4:
        return "夺利"
    if coop > 0.62 and agg < 0.4:
        return "互助合作"
    if agg < 0.35 and coop < 0.35 and met < 0.4:
        return "修身"
    if agg > 0.55 and coop > 0.55:
        return "好善疾恶"
    if 0.4 <= agg <= 0.65 and 0.4 <= coop <= 0.65:
        return "未分化"
    return "中间态"


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
    def __init__(self, w: int = PLAY_W, h: int = PLAY_H) -> None:
        self.w = w
        self.h = h
        self.agents: List[Agent] = []
        self.food: List[Tuple[float, float, float]] = []  # (x, y, amount)
        self.tick = 0
        self.births = 0
        self.deaths = 0
        # per-tick metric history (ring buffer of length HISTORY_MAX)
        self.good_hist: List[float] = []     # fraction with cooperation > threshold
        self.pop_hist: List[int] = []
        self.agg_hist: List[float] = []
        self.coop_hist: List[float] = []
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

        # periodic telemetry (DEBUG_TELEMETRY=1)
        import os
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
    def good_rate(self) -> float:
        """Fraction of agents whose cooperation trait exceeds GOOD_COOP_THRESHOLD."""
        if not self.agents:
            return 0.0
        n = sum(1 for a in self.agents if a.traits["cooperation"] > GOOD_COOP_THRESHOLD)
        return n / len(self.agents)

    def _avg_trait(self, name: str) -> float:
        if not self.agents:
            return 0.0
        return sum(a.traits[name] for a in self.agents) / len(self.agents)

    def _record_metrics(self) -> None:
        self.good_hist.append(self.good_rate())
        self.pop_hist.append(len(self.agents))
        self.agg_hist.append(self._avg_trait("aggression"))
        self.coop_hist.append(self._avg_trait("cooperation"))
        # trim to ring buffer length
        for h in (self.good_hist, self.pop_hist, self.agg_hist, self.coop_hist):
            if len(h) > HISTORY_MAX:
                del h[: len(h) - HISTORY_MAX]
        # track stage transitions (only when stage actually changes)
        stage = self.current_stage()
        if stage != self._last_stage:
            self.stage_transitions.append({"tick": self.tick, "stage": stage})
            self._last_stage = stage

    def current_stage(self) -> str:
        """Classify the current population into a book-derived label.
        Order matters — first matching rule wins."""
        if not self.agents:
            return "空"
        if self.tick < 60:
            return "起始混乱"

        pop = len(self.agents)
        agg = self._avg_trait("aggression")
        coop = self._avg_trait("cooperation")
        good = self.good_rate()

        # pop trend over last ~60 ticks
        window = self.pop_hist[-60:] if len(self.pop_hist) >= 60 else self.pop_hist[:]
        pop_delta = (window[-1] - window[0]) if len(window) >= 2 else 0

        # collapse = both pop falling AND cooperation dying
        if pop < 25:
            return "濒临灭绝"
        if agg > 0.72 and coop < 0.40:
            return "霍布斯丛林"
        # 伊甸园: sustained high coop + low agg + pop stable
        if coop > 0.55 and agg < 0.50 and abs(pop_delta) < 20:
            return "伊甸园期"
        # 合作繁荣中: coop high + pop growing fast
        if coop > 0.50 and agg < 0.55 and pop_delta > 25:
            return "合作繁荣中"
        # 维度坍缩: pop crashing hard
        if pop_delta < -40:
            return "维度坍缩中"
        # 夺利丛林 (clearly red)
        if agg > 0.62:
            return "夺利丛林"
        # 朴素合作 (visible green cluster)
        if coop > 0.48 and good > 0.35:
            return "朴素合作"
        # 修身主导
        if agg < 0.40 and coop < 0.40:
            return "修身主导"
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
        import os
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
            hue = trait_hue(a.traits)
            # saturation a bit muted, lightness by energy
            sat = 0.55 + 0.35 * (1.0 - abs(a.traits["aggression"] - a.traits["cooperation"]))
            light = 0.45 + 0.25 * (a.energy / MAX_ENERGY)
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

        # strategy counts (top 3)
        if world.agents:
            counts: dict[str, int] = {}
            for a in world.agents:
                lbl = strategy_label(a.traits)
                counts[lbl] = counts.get(lbl, 0) + 1
            top = sorted(counts.items(), key=lambda kv: -kv[1])[:3]
            txt = "  ".join(f"{k} {v}" for k, v in top)
            self.screen.blit(self.font.render("策略占比 " + txt, True, HUD_FG),
                             (12, 60))

        # ===== STAGE LABEL + 善者存活率 SPARKLINE =====
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
        self.screen.blit(self.font.render(
            f"善者存活率（合作 > {GOOD_COOP_THRESHOLD:.1f}）：{good*100:5.1f}%",
            True, HUD_DIM), (12, 110))

        # sparkline of 善者存活率 (right-aligned with histograms)
        sp_x = WORLD_W - 230
        sp_y = 96
        sp_w = 220
        sp_h = 24
        # background
        pygame.draw.rect(self.screen, (28, 28, 38),
                         (sp_x, sp_y, sp_w, sp_h))
        # 0.5 reference line
        pygame.draw.line(self.screen, (50, 50, 60),
                         (sp_x, sp_y + sp_h // 2),
                         (sp_x + sp_w, sp_y + sp_h // 2), 1)
        # the line itself
        hist = world.good_hist
        if len(hist) >= 2:
            pts = []
            for i, v in enumerate(hist):
                px = sp_x + int(i * sp_w / HISTORY_MAX)
                py = sp_y + sp_h - int(v * sp_h)
                pts.append((px, py))
            pygame.draw.lines(self.screen, (110, 220, 150), False, pts, 2)
        self.screen.blit(self.font_lbl.render("善者存活率  0.5", True, HUD_DIM),
                         (sp_x, sp_y - 12))

        # trait histograms (aggression, cooperation) on right side
        if world.agents:
            bins_a = [0] * 10
            bins_c = [0] * 10
            for a in world.agents:
                bins_a[min(9, int(a.traits["aggression"] * 10))] += 1
                bins_c[min(9, int(a.traits["cooperation"] * 10))] += 1
            # agg
            self.screen.blit(self.font_lbl.render("aggression", True, HUD_DIM),
                             (sp_x, 8))
            self._bars(bins_a, sp_x, 18, 100, 14)
            # coop
            self.screen.blit(self.font_lbl.render("cooperation", True, HUD_DIM),
                             (sp_x + 110, 8))
            self._bars(bins_c, sp_x + 110, 18, 100, 14)

            # frame counter so the user can SEE the loop is running
            self.screen.blit(self.font_lbl.render(
                f"frame {frame}  step-err {self.step_errors}",
                True, HUD_DIM), (sp_x, 122))

        # bottom bar
        pygame.draw.rect(self.screen, (20, 20, 28),
                         (0, WORLD_H - HUD_BOTTOM_H, WORLD_W, HUD_BOTTOM_H))
        help_txt = ("SPACE pause · R reset · N inject agent · F drop food · "
                    "+/- speed · ESC quit   |   click in play area to apply current mode")
        self.screen.blit(self.font.render(help_txt, True, HUD_DIM),
                         (12, WORLD_H - HUD_BOTTOM_H + 18))

    def _bars(self, bins, x, y, w, h) -> None:
        if not bins:
            return
        m = max(bins) or 1
        bar_w = w // len(bins)
        for i, b in enumerate(bins):
            bh = int(h * b / m)
            pygame.draw.rect(
                self.screen,
                _hls_to_rgb(i / len(bins) * 0.8 + 0.05, 0.55, 0.7),
                (x + i * bar_w, y + h - bh, bar_w - 1, bh),
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

def save_run(world: World, ended_reason: str) -> Path | None:
    """Dump the current world state + per-tick metrics history to a timestamped
    JSON file under runs/. Returns the saved path, or None on failure."""
    try:
        RUNS_DIR.mkdir(exist_ok=True)
        ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        path = RUNS_DIR / f"{ts}.json"
        # build time-series (downsampled if too long, but keep all transitions)
        n = len(world.pop_hist)
        history = [
            {
                "tick": i,
                "pop": world.pop_hist[i],
                "agg": round(world.agg_hist[i], 4),
                "coop": round(world.coop_hist[i], 4),
                "good": round(world.good_hist[i], 4),
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
                            speed = max(0.25, speed - 0.5)
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