#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
岁岁 (Suisui) — 可爱的蓝猫桌面宠物
A cute blue cat desktop pet for macOS

作者: Sue Tech
"""

import tkinter as tk
from tkinter import Menu
import math
import random
import subprocess
import threading
import time
import os


# ─────────────────────────────────────────
# 常量 / Constants
# ─────────────────────────────────────────
CAT_W, CAT_H = 130, 140          # canvas size
SCREEN_MARGIN = 10               # pixels from screen edge
WALK_SPEED = 2                   # pixels per frame
FRAME_MS = 60                    # ms between frames (~16fps)
IDLE_BLINK_INTERVAL = 4000       # ms between blinks
REMINDER_INTERVAL = 45 * 60 * 1000  # 45 minutes in ms
BUBBLE_DURATION = 5000           # ms speech bubble stays up
HIDE_DURATION = 30 * 60 * 1000  # 30 minutes "sleep" duration

REMINDER_MESSAGES = [
    "主人，起来动一动吧！🦵",
    "喝水时间到啦～ 💧",
    "久坐伤身，站一会儿吧！🌸",
    "记得眨眨眼，保护视力哦 👀",
]

# Colors
BODY_BLUE    = "#2C3154"
EAR_INNER    = "#FF7A59"
NOSE_COLOR   = "#FF7A59"
EYE_WHITE    = "#FFFFFF"
EYE_PUPIL    = "#1A1A2E"
EYE_SHINE    = "#FFFFFF"
BELLY_LIGHT  = "#3D4278"
CHEEK_COLOR  = "#FF9999"
STRIPE_COLOR = "#222845"
BUBBLE_BG    = "#FFFEF0"
BUBBLE_BORDER= "#FFCC44"


# ─────────────────────────────────────────
# 主应用 / Main App
# ─────────────────────────────────────────
class SuisuiApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self._setup_window()

        # State
        self.state = "walk"         # walk | sit | happy | sleep | remind
        self.direction = 1          # 1 = right, -1 = left
        self.walk_frame = 0         # animation frame counter
        self.blink_open = True      # eyes open or closed
        self.happy_shake = 0        # shake counter for happy state
        self.bubble_text = ""       # current speech bubble text
        self.bubble_visible = False
        self.sleeping = False

        # Window position
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        self.screen_w = sw
        self.screen_h = sh
        start_x = sw // 2
        start_y = sh - CAT_H - SCREEN_MARGIN - 40
        self.cat_x = float(start_x)  # cat center x on screen
        self.cat_y = float(start_y)  # cat top-left y on screen

        # Canvas (transparent)
        self.canvas = tk.Canvas(
            root,
            width=CAT_W, height=CAT_H + 60,  # extra space for bubble above
            bg="systemTransparent",
            highlightthickness=0,
        )
        self.canvas.pack()

        # Bind events
        self.canvas.bind("<Button-1>", self._on_left_click)
        self.canvas.bind("<Button-2>", self._on_right_click)
        self.canvas.bind("<Button-3>", self._on_right_click)

        # Drag support for file-to-trash
        self.root.bind("<B1-Motion>", self._on_drag)

        # Enable window dragging
        self._drag_start_x = 0
        self._drag_start_y = 0
        self.canvas.bind("<ButtonPress-1>", self._drag_start)
        self.canvas.bind("<B1-Motion>", self._drag_motion)

        # Start loops
        self._position_window()
        self._animation_loop()
        self._schedule_blink()
        self._schedule_reminder()

    # ── Window Setup ──────────────────────
    def _setup_window(self):
        """Configure the transparent always-on-top window."""
        root = self.root
        root.overrideredirect(True)       # No title bar / chrome
        root.attributes("-topmost", True) # Always on top
        root.attributes("-transparent", True)
        root.configure(bg="systemTransparent")
        root.wm_attributes("-alpha", 1.0)

    def _position_window(self):
        """Move the OS window to match self.cat_x / self.cat_y."""
        win_x = int(self.cat_x) - CAT_W // 2
        win_y = int(self.cat_y) - 60  # 60px bubble space above cat
        self.root.geometry(f"{CAT_W}x{CAT_H + 60}+{win_x}+{win_y}")

    # ── Animation Loop ────────────────────
    def _animation_loop(self):
        """Main loop: update state then redraw."""
        if not self.sleeping:
            self._update_state()
        self._draw()
        self.root.after(FRAME_MS, self._animation_loop)

    def _update_state(self):
        """Move cat and advance animations."""
        if self.state == "walk":
            self.cat_x += WALK_SPEED * self.direction
            self.walk_frame = (self.walk_frame + 1) % 20  # 20-frame walk cycle

            # Boundary check
            left_bound  = CAT_W // 2 + SCREEN_MARGIN
            right_bound = self.screen_w - CAT_W // 2 - SCREEN_MARGIN
            if self.cat_x >= right_bound:
                self.direction = -1
                self.cat_x = right_bound
            elif self.cat_x <= left_bound:
                self.direction = 1
                self.cat_x = left_bound

        elif self.state == "happy":
            self.happy_shake += 1
            if self.happy_shake > 40:   # shake for ~2.5 seconds
                self.happy_shake = 0
                self.state = "walk"

        elif self.state == "remind":
            # Walk toward center
            center_x = self.screen_w / 2
            dist = center_x - self.cat_x
            if abs(dist) > 5:
                self.direction = 1 if dist > 0 else -1
                self.cat_x += WALK_SPEED * 2 * self.direction
                self.walk_frame = (self.walk_frame + 1) % 20
            else:
                # Arrived at center — show bubble
                self.state = "sit"
                self._show_bubble(random.choice(REMINDER_MESSAGES))

    # ── Drawing ───────────────────────────
    def _draw(self):
        """Clear canvas and draw everything."""
        c = self.canvas
        c.delete("all")

        # Bubble offset (60px header space)
        bub_top = 0
        cat_top = 60  # cat drawn starting at y=60

        # Draw speech bubble if visible
        if self.bubble_visible and self.bubble_text:
            self._draw_bubble(c, bub_top)

        # Draw cat at cat_top
        self._draw_cat(c, CAT_W // 2, cat_top)

    def _draw_bubble(self, c, y_offset):
        """Draw a cute speech bubble at top of canvas."""
        bx, by = 5, y_offset + 2
        bw, bh = CAT_W - 10, 50
        r = 10  # corner radius

        # Rounded rect
        c.create_arc(bx,      by,      bx+2*r, by+2*r, start=90,  extent=90,  fill=BUBBLE_BG, outline=BUBBLE_BORDER, width=2)
        c.create_arc(bw-r*2+bx, by,    bw+bx,  by+2*r, start=0,   extent=90,  fill=BUBBLE_BG, outline=BUBBLE_BORDER, width=2)
        c.create_arc(bx,      bh-2*r+by, bx+2*r, bh+by, start=180, extent=90,  fill=BUBBLE_BG, outline=BUBBLE_BORDER, width=2)
        c.create_arc(bw-r*2+bx, bh-2*r+by, bw+bx, bh+by, start=270, extent=90, fill=BUBBLE_BG, outline=BUBBLE_BORDER, width=2)
        # fill rects
        c.create_rectangle(bx+r, by,    bw+bx-r, bh+by, fill=BUBBLE_BG, outline="")
        c.create_rectangle(bx,   by+r,  bw+bx,   bh+by-r, fill=BUBBLE_BG, outline="")
        # border lines
        c.create_line(bx+r, by,    bw+bx-r, by,    fill=BUBBLE_BORDER, width=2)
        c.create_line(bx+r, bh+by, bw+bx-r, bh+by, fill=BUBBLE_BORDER, width=2)
        c.create_line(bx,   by+r,  bx,      bh+by-r, fill=BUBBLE_BORDER, width=2)
        c.create_line(bw+bx, by+r, bw+bx,  bh+by-r, fill=BUBBLE_BORDER, width=2)

        # Tail (triangle pointing down toward cat)
        tail_x = CAT_W // 2
        c.create_polygon(
            tail_x-8, bh+by,
            tail_x+8, bh+by,
            tail_x,   bh+by+10,
            fill=BUBBLE_BG, outline=BUBBLE_BORDER, width=2
        )

        # Text
        c.create_text(
            CAT_W // 2, by + bh // 2,
            text=self.bubble_text,
            font=("PingFang SC", 10, "bold"),
            fill="#333333",
            width=bw - 10,
            anchor="center",
        )

    def _draw_cat(self, c, cx, top):
        """Draw the full chibi cat centered at cx, starting at top."""
        # Leg/body bob from walking
        bob = 0
        leg_swing = 0
        shake_x = 0
        if self.state == "walk":
            bob = int(math.sin(self.walk_frame * math.pi / 5) * 2)
            leg_swing = int(math.sin(self.walk_frame * math.pi / 5) * 5)
        elif self.state == "happy":
            shake_x = int(math.sin(self.happy_shake * math.pi / 4) * 6)
            bob = int(abs(math.sin(self.happy_shake * math.pi / 4)) * 4)

        # Flip direction (mirror for left-walk)
        flip = self.direction  # 1 or -1

        # ── Tail ──
        tail_base_x = cx - 20 * flip + shake_x
        tail_base_y = top + 95 + bob
        cp1x = cx - 40 * flip + shake_x
        cp1y = top + 80 + bob
        cp2x = cx - 55 * flip + shake_x
        cp2y = top + 100 + bob
        tail_tip_x = cx - 45 * flip + shake_x
        tail_tip_y = top + 115 + bob
        self._draw_bezier_tail(c, tail_base_x, tail_base_y, cp1x, cp1y, cp2x, cp2y, tail_tip_x, tail_tip_y)

        # ── Body ──
        bx1 = cx - 22 + shake_x
        by1 = top + 72 + bob
        bx2 = cx + 22 + shake_x
        by2 = top + 108 + bob
        c.create_oval(bx1, by1, bx2, by2, fill=BODY_BLUE, outline="")
        # Belly lighter patch
        c.create_oval(cx - 12 + shake_x, by1 + 8, cx + 12 + shake_x, by2 - 4,
                      fill=BELLY_LIGHT, outline="")

        # ── Legs ──
        self._draw_legs(c, cx, top, bob, leg_swing, flip, shake_x)

        # ── Head ── (drawn after body so it's on top)
        hcx = cx + shake_x
        hcy = top + 48 + bob
        hr  = 38  # head radius

        # Ears (behind head)
        self._draw_ears(c, hcx, hcy, hr, flip)

        # Head circle
        c.create_oval(hcx - hr, hcy - hr, hcx + hr, hcy + hr,
                      fill=BODY_BLUE, outline="")

        # Forehead stripe (cute tabby mark)
        for i, dy in enumerate([-10, -2, 6]):
            w = 12 - i * 3
            c.create_line(hcx - w // 2, hcy - 20 + dy,
                          hcx + w // 2, hcy - 20 + dy,
                          fill=STRIPE_COLOR, width=2, capstyle="round")

        # ── Eyes ──
        self._draw_eyes(c, hcx, hcy, flip)

        # ── Nose & Mouth ──
        c.create_oval(hcx - 5, hcy + 10, hcx + 5, hcy + 17,
                      fill=NOSE_COLOR, outline="")
        # Mouth
        c.create_arc(hcx - 8, hcy + 14, hcx,     hcy + 22,
                     start=180, extent=-90, style="arc", outline="#FFAA88", width=1)
        c.create_arc(hcx,     hcy + 14, hcx + 8,  hcy + 22,
                     start=270, extent=-90, style="arc", outline="#FFAA88", width=1)

        # Whiskers
        wx = 10
        for side in [-1, 1]:
            for i, wy in enumerate([-2, 2, 6]):
                x0 = hcx + side * 6
                x1 = hcx + side * (6 + wx + (i == 1) * 4)
                y0 = hcy + 12 + wy
                y1 = hcy + 12 + wy + side * i
                c.create_line(x0, y0, x1, y1,
                              fill="#8899CC", width=1, capstyle="round")

        # Cheek blush
        c.create_oval(hcx - 32, hcy + 4, hcx - 18, hcy + 16,
                      fill=CHEEK_COLOR, outline="", stipple="gray50")
        c.create_oval(hcx + 18, hcy + 4, hcx + 32, hcy + 16,
                      fill=CHEEK_COLOR, outline="", stipple="gray50")

    def _draw_ears(self, c, hcx, hcy, hr, flip):
        """Draw two pointy ears."""
        for side in [-1, 1]:
            ex = hcx + side * 25
            ey = hcy - hr + 8
            # Outer ear
            c.create_polygon(
                ex - 10, ey + 6,
                ex + 10, ey + 6,
                ex + side * 6, ey - 20,
                fill=BODY_BLUE, outline=""
            )
            # Inner ear (orange)
            c.create_polygon(
                ex - 6, ey + 4,
                ex + 6, ey + 4,
                ex + side * 3, ey - 12,
                fill=EAR_INNER, outline=""
            )

    def _draw_eyes(self, c, hcx, hcy, flip):
        """Draw eyes — open, half, or closed based on state."""
        eye_offsets = [(-16, 0), (16, 0)]
        eye_r = 10

        for ex_off, ey_off in eye_offsets:
            ex = hcx + ex_off
            ey = hcy - 4 + ey_off

            if not self.blink_open or self.state == "sleep":
                # Closed eyes: curved line
                c.create_arc(ex - eye_r, ey - eye_r // 2,
                             ex + eye_r, ey + eye_r // 2,
                             start=0, extent=180,
                             style="arc", outline=EYE_WHITE, width=2)
            elif self.state == "happy":
                # Happy ^ ^ eyes
                c.create_arc(ex - eye_r, ey - eye_r // 2,
                             ex + eye_r, ey + eye_r // 2,
                             start=0, extent=180,
                             style="arc", outline=EYE_WHITE, width=3)
            else:
                # Normal open eyes
                c.create_oval(ex - eye_r, ey - eye_r, ex + eye_r, ey + eye_r,
                              fill=EYE_WHITE, outline="")
                # Pupil
                c.create_oval(ex - 6, ey - 6, ex + 6, ey + 6,
                              fill=EYE_PUPIL, outline="")
                # Shine
                c.create_oval(ex + 1, ey - 5, ex + 5, ey - 1,
                              fill=EYE_SHINE, outline="")
                # Eyelash top line
                c.create_arc(ex - eye_r, ey - eye_r,
                             ex + eye_r, ey + eye_r,
                             start=20, extent=140,
                             style="arc", outline=BODY_BLUE, width=2)

    def _draw_legs(self, c, cx, top, bob, leg_swing, flip, shake_x):
        """Draw four stubby legs with slight walk swing."""
        # Front legs
        for side, swing_mul in [(-1, 1), (1, -1)]:
            lx = cx + side * 14 + shake_x
            ly_top = top + 96 + bob
            swing = leg_swing * swing_mul * flip
            c.create_oval(lx - 7, ly_top + swing,
                          lx + 7, ly_top + 18 + swing,
                          fill=BODY_BLUE, outline="")
            # Paw
            c.create_oval(lx - 7, ly_top + 14 + swing,
                          lx + 7, ly_top + 22 + swing,
                          fill=BELLY_LIGHT, outline="")

    def _draw_bezier_tail(self, c, x0, y0, x1, y1, x2, y2, x3, y3, steps=20):
        """Draw a smooth cubic bezier tail using line segments."""
        pts = []
        for i in range(steps + 1):
            t = i / steps
            u = 1 - t
            x = u**3*x0 + 3*u**2*t*x1 + 3*u*t**2*x2 + t**3*x3
            y = u**3*y0 + 3*u**2*t*y1 + 3*u*t**2*y2 + t**3*y3
            pts.extend([x, y])
        if len(pts) >= 4:
            self.canvas.create_line(*pts, fill=BODY_BLUE, width=8,
                                    capstyle="round", joinstyle="round", smooth=True)
            # Tail tip lighter
            self.canvas.create_oval(x3 - 6, y3 - 6, x3 + 6, y3 + 6,
                                    fill=BELLY_LIGHT, outline="")

    # ── Speech Bubble ─────────────────────
    def _show_bubble(self, text: str, duration_ms: int = BUBBLE_DURATION):
        """Show a speech bubble for duration_ms milliseconds."""
        self.bubble_text = text
        self.bubble_visible = True
        self.root.after(duration_ms, self._hide_bubble)

    def _hide_bubble(self):
        self.bubble_visible = False
        self.bubble_text = ""
        if self.state == "sit":
            self.state = "walk"

    # ── Blink ─────────────────────────────
    def _schedule_blink(self):
        self.root.after(IDLE_BLINK_INTERVAL + random.randint(-1000, 1000),
                        self._do_blink)

    def _do_blink(self):
        self.blink_open = False
        self.root.after(150, self._open_eyes)

    def _open_eyes(self):
        self.blink_open = True
        self._schedule_blink()

    # ── Reminder ──────────────────────────
    def _schedule_reminder(self):
        self.root.after(REMINDER_INTERVAL, self._do_reminder)

    def _do_reminder(self):
        if not self.sleeping:
            self.state = "remind"
        self._schedule_reminder()

    # ── Interactions ──────────────────────
    def _on_left_click(self, event):
        """Left click — detect head vs belly area."""
        # Canvas coords; cat is drawn with cat_top=60
        cat_top = 60
        # Head center roughly at (CAT_W//2, cat_top + 48)
        head_cy = cat_top + 48
        head_r  = 40
        dist = math.hypot(event.x - CAT_W // 2, event.y - head_cy)
        if dist < head_r:
            self._pet_head()
        else:
            self._poke_belly()

    def _pet_head(self):
        """Pet the cat on the head — happy reaction."""
        self.state = "happy"
        self.happy_shake = 0
        self.blink_open = False
        self._show_bubble("嗯嗯～", duration_ms=2500)
        self.root.after(300, lambda: setattr(self, "blink_open", True))

    def _poke_belly(self):
        """Click belly — meow!"""
        # Try system sound, fall back to bubble
        try:
            subprocess.Popen(
                ["afplay", "/System/Library/Sounds/Tink.aiff"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
        except Exception:
            pass
        self._show_bubble("喵！", duration_ms=2000)

    def _on_right_click(self, event):
        """Right-click context menu."""
        menu = Menu(self.root, tearoff=0,
                    font=("PingFang SC", 12),
                    bg="#FFFEF0", fg="#333333",
                    activebackground=BUBBLE_BORDER)
        menu.add_command(label="💤 去睡觉 (30分钟)", command=self._go_sleep)
        menu.add_command(label="⏰ 提醒设置",        command=self._show_reminder_info)
        menu.add_separator()
        menu.add_command(label="👋 退出",            command=self.root.quit)
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    # ── Sleep ──────────────────────────────
    def _go_sleep(self):
        self.sleeping = True
        self.state = "sleep"
        self.blink_open = False
        self._show_bubble("Zzz...", duration_ms=HIDE_DURATION)
        # Minimize visibility by going mostly transparent
        self.root.wm_attributes("-alpha", 0.3)
        self.root.after(HIDE_DURATION, self._wake_up)

    def _wake_up(self):
        self.sleeping = False
        self.state = "walk"
        self.blink_open = True
        self.bubble_visible = False
        self.root.wm_attributes("-alpha", 1.0)

    def _show_reminder_info(self):
        self._show_bubble("每45分钟提醒一次！", duration_ms=3000)

    # ── Window Drag ───────────────────────
    def _drag_start(self, event):
        self._drag_start_x = event.x_root - self.root.winfo_x()
        self._drag_start_y = event.y_root - self.root.winfo_y()

    def _drag_motion(self, event):
        new_win_x = event.x_root - self._drag_start_x
        new_win_y = event.y_root - self._drag_start_y
        self.root.geometry(f"+{new_win_x}+{new_win_y}")
        # Update logical position
        self.cat_x = new_win_x + CAT_W // 2
        self.cat_y = new_win_y + 60

    def _on_drag(self, event):
        """Placeholder — file drop requires OS-level support."""
        pass


# ─────────────────────────────────────────
# File-to-Trash Drop Handler (best-effort)
# ─────────────────────────────────────────
def move_to_trash(filepath: str):
    """Move a file to macOS Trash via osascript."""
    script = f'tell application "Finder" to delete POSIX file "{filepath}"'
    try:
        subprocess.run(["osascript", "-e", script],
                       capture_output=True, timeout=10)
    except Exception as e:
        print(f"[岁岁] Trash error: {e}")


# ─────────────────────────────────────────
# Entry Point
# ─────────────────────────────────────────
def main():
    root = tk.Tk()

    # ── macOS transparent overlay setup ──
    root.overrideredirect(True)
    root.attributes("-topmost", True)
    root.attributes("-transparent", True)
    root.configure(bg="systemTransparent")
    root.wm_attributes("-alpha", 1.0)

    app = SuisuiApp(root)

    # Position initially at bottom center
    root.update_idletasks()
    app._position_window()

    root.mainloop()


if __name__ == "__main__":
    main()
