import calendar, pygame, random, math, json, datetime, subprocess, sys, wave, threading, socket, queue, webbrowser, urllib.parse
import numpy as np
from pathlib import Path

# Arrow Puzzle - fully packed grid, snake-style escape animation, working modes/themes
# Install once: python -m pip install pygame numpy
# Run: python arrow_puzzle_complete_fixed.py
pygame.init()
SFX = {}
combo = 0
finale_start = 0
sound_on = True; vibe_on = True; autolock_on = False   # Settings page toggles
shake_until = 0; last_input_ms = 0; AUTOLOCK_MS = 60000
daily_date = None; daily_complete = False; daily_open_t = 0   # which Daily Challenge date is being played / finished pop-up
progress = {}           # saved level progress per mode: {'Classic': {'level': 5, 'score': 420}}
pending = []            # (due_ms, function): delayed events, e.g. the Diwali finale after the last "oops"
SEMI = [0, 2, 4, 7, 9, 12, 14, 16, 19, 21]    # rising major-pentatonic steps for the combo pops

def _make_sound(mono, volume):
    """mono: float array in [-1,1] -> pygame Sound matching the mixer's channels."""
    freq, fmt, ch = pygame.mixer.get_init()
    data = (np.clip(mono, -1, 1) * 32767 * volume).astype(np.int16)
    if ch == 2: data = np.repeat(data[:, None], 2, axis=1)
    return pygame.mixer.Sound(buffer=np.ascontiguousarray(data).tobytes())

def _norm(x): return x / max(1e-6, np.abs(x).max())

def _place(mix, w, start, sr, gain=1.0):
    i = int(start*sr); e = min(len(mix), i+len(w))
    if e > i: mix[i:e] += w[:e-i]*gain

def _echo(x, sr, delay=0.2, fb=0.35, n=3):
    out = x.copy()
    for k in range(1, n+1):
        d = int(sr*delay*k)
        if d < len(x): out[d:] += x[:len(x)-d]*(fb**k)
    return out

# ---------- building blocks ----------
def _whoosh(dur, sr, seed=1, lo=250, hi=3200):      # swept low-pass noise = air whoosh
    n = int(sr*dur); x = np.random.default_rng(seed).standard_normal(n); t = np.linspace(0, 1, n)
    a = 1-np.exp(-2*np.pi*(lo+(hi-lo)*np.sin(np.pi*t))/sr); y = np.zeros(n); p = 0.0
    for i in range(n):
        p += a[i]*(x[i]-p); y[i] = p
    return _norm(y*np.sin(np.pi*t)**1.5)

def _bloop(f0, sr, dur=0.18):                       # bubble pop
    t = np.arange(int(sr*dur))/sr; f = f0*(1+0.9*np.minimum(1, t/0.035))
    return np.sin(2*np.pi*np.cumsum(f)/sr)*np.exp(-t*26)*np.minimum(1, t/0.002)

def _chirp(f0, f1, dur, sr, decay=12):
    t = np.arange(int(sr*dur))/sr; f = f0+(f1-f0)*t/dur
    return np.sin(2*np.pi*np.cumsum(f)/sr)*np.exp(-t*decay)*np.minimum(1, t/0.003)

def _cpop(sr, seed):                                # small cracker "pat"
    rng = np.random.default_rng(seed); n = int(sr*0.09); t = np.arange(n)/sr; x = rng.standard_normal(n)
    x = x-np.convolve(x, np.ones(5)/5, 'same')
    return x*np.exp(-t*85)+0.6*np.sin(2*np.pi*150*t)*np.exp(-t*60)

def _boom(sr, seed, dur=1.4, f0=90):                # big bomb / rocket burst
    rng = np.random.default_rng(seed); n = int(sr*dur); t = np.arange(n)/sr
    thump = np.sin(2*np.pi*np.cumsum(f0*np.exp(-t*2.2)+28)/sr)*np.exp(-t*3.0)
    noise = rng.standard_normal(n)
    rumble = np.convolve(noise, np.ones(36)/36, 'same')*np.exp(-t*3.5)*6
    crack = (noise-np.convolve(noise, np.ones(4)/4, 'same'))*np.exp(-t*35)*1.2
    return thump*1.2+rumble+crack

def _whistle(sr, dur, f0, f1):                      # rocket going up
    n = int(sr*dur); t = np.arange(n)/sr; f = f0*(f1/f0)**(t/dur)
    amp = (0.25+0.75*t/dur)*np.minimum(1, (dur-t)/0.04)
    return np.sin(2*np.pi*np.cumsum(f)/sr)*amp*0.6

def _crackle(sr, dur, seed, density):               # sparkle crackle after a burst
    rng = np.random.default_rng(seed); n = int(sr*dur); t = np.arange(n)/sr
    imp = (rng.random(n) < density*np.exp(-t*2.0))*rng.standard_normal(n)
    kern = rng.standard_normal(110)*np.exp(-np.arange(110)/16)
    return np.convolve(imp, kern)[:n]*1.5

FX_TIMELINES = {}
def _diwali(sr, long):
    """Diwali: cracker string (ladi), atom bombs, rockets with burst + crackle, big finale.
    Also returns the timeline of bangs so the on-screen lights can flash in sync."""
    rng = np.random.default_rng(11); total = 10.6 if long else 5.8; m = np.zeros(int(sr*total)); ev = []
    t = 0.0
    for k in range(34 if long else 16):
        _place(m, _cpop(sr, k), t, sr, float(rng.uniform(0.5, 1.0))); ev.append((t, 'pop')); t += float(rng.uniform(0.022, 0.085))
    t += 0.12
    _place(m, _boom(sr, 1, 1.0, 120), t, sr, 0.9); ev.append((t, 'boom'))
    _place(m, _boom(sr, 2, 1.2, 100), t+0.35, sr, 1.0); ev.append((t+0.35, 'boom'))
    starts = [t+0.9, t+2.1, t+3.3, t+4.4] if long else [t+0.7, t+1.4]
    for i, t0 in enumerate(starts):
        _place(m, _whistle(sr, 0.7, 450, 2000+i*350), t0, sr, 0.35)
        _place(m, _boom(sr, 10+i, 1.4, 75+i*9), t0+0.7, sr, 1.0)
        _place(m, _crackle(sr, 1.5, 20+i, 0.004), t0+0.75, sr, 0.6); ev.append((t0, 'launch', t0+0.7))
    tf = (t+5.6) if long else (t+2.7)
    fin = ((0, 1.0), (0.14, 0.8), (0.3, 1.0), (0.5, 0.9), (0.75, 1.0)) if long else ((0, 1.0), (0.18, 0.9), (0.4, 1.0))
    for dt, g in fin:
        _place(m, _boom(sr, 40+int(dt*100), 1.5, 85), tf+dt, sr, g); ev.append((tf+dt, 'boom'))
    _place(m, _crackle(sr, 2.2 if long else 1.2, 77, 0.006), tf+0.1, sr, 0.7)
    return _norm(_echo(m, sr, 0.28, 0.3, 2)), sorted(ev)

# ---------- "Oops!" ----------
def _vowel(sr, dur, f0a, f0b, formants):
    n = int(sr*dur); t = np.arange(n)/sr; f0 = f0a+(f0b-f0a)*t/dur; ph = 2*np.pi*np.cumsum(f0)/sr
    src = sum(np.sin(k*ph)/k for k in range(1, 25)); fr = np.fft.rfftfreq(n, 1/sr)
    env = 0.02+sum(g*np.exp(-0.5*((fr-fc)/bw)**2) for fc, bw, g in formants)
    y = np.fft.irfft(np.fft.rfft(src)*env, n)
    return _norm(y)*np.minimum(1, t/0.02)*np.minimum(1, (dur-t)/0.05)

def _oops_synth(sr):
    """Fallback: a soft, high, cute synthesized 'oops' (used when no Windows voice is available)."""
    rng = np.random.default_rng(5); m = np.zeros(int(sr*0.85))
    _place(m, _vowel(sr, 0.12, 440, 480, [(500, 70, 1), (900, 90, .8), (2500, 150, .2)]), 0.0, sr, 0.8)     # "oh"
    _place(m, _vowel(sr, 0.30, 480, 330, [(320, 60, 1), (800, 90, .35)]), 0.10, sr, 1.0)                     # falling "oo"
    _place(m, _cpop(sr, 3)*0.4, 0.43, sr, 0.4)
    n = int(sr*0.12); x = rng.standard_normal(n); x = x-np.convolve(x, np.ones(3)/3, 'same')
    _place(m, x*np.sin(np.pi*np.linspace(0, 1, n))**1.2, 0.5, sr, 0.25)
    return _norm(m)

def _oops_voice(sr):
    """A sweet 'Oops!' from the Windows female voice, pitched up a little (made once -> oops_sweet.wav)."""
    try:
        wav = Path(__file__).with_name('oops_sweet.wav')
        if not wav.exists() and sys.platform == 'win32':
            path = str(wav).replace("'", "''")
            ps = ("Add-Type -AssemblyName System.Speech; $s=New-Object System.Speech.Synthesis.SpeechSynthesizer; "
                  "try{$s.SelectVoiceByHints([System.Speech.Synthesis.VoiceGender]::Female)}catch{}; $s.Volume=100; $s.Rate=-1; "
                  f"$s.SetOutputToWaveFile('{path}'); $s.Speak('Oops!'); $s.Dispose()")
            subprocess.run(['powershell', '-NoProfile', '-Command', ps], timeout=25, capture_output=True, creationflags=0x08000000)
        if not wav.exists(): return None
        with wave.open(str(wav), 'rb') as w:
            ch, sw, fr = w.getnchannels(), w.getsampwidth(), w.getframerate(); raw = w.readframes(w.getnframes())
        if sw != 2: return None
        x = np.frombuffer(raw, dtype=np.int16).astype(np.float64)/32768
        if ch > 1: x = x.reshape(-1, ch).mean(axis=1)
        idx = np.where(np.abs(x) > 0.02)[0]
        if len(idx) < 10: return None
        x = x[max(0, idx[0]-200): idx[-1]+400]
        pos = np.arange(0, len(x)-1, 1.18*fr/sr)               # play a bit faster = sweeter, higher voice
        y = np.interp(pos, np.arange(len(x)), x)
        y *= np.minimum(1, np.arange(len(y))/(0.01*sr))*np.minimum(1, (len(y)-np.arange(len(y)))/(0.05*sr))
        return _make_sound(_norm(y), 0.95)
    except Exception:
        return None

def _build_sounds():
    pygame.mixer.init(); sr = pygame.mixer.get_init()[0]
    Z = lambda d: np.zeros(int(sr*d))
    for i, semi in enumerate(SEMI):               # arrow escapes: whoosh + bubble pop, pitch climbs with your combo
        f = 480*2**(semi/12); m = Z(0.4)
        _place(m, _whoosh(0.16, sr, i)*0.5, 0, sr); _place(m, _bloop(f, sr), 0.07, sr)
        SFX[f'pluck{i}'] = _make_sound(_norm(m), 0.6)
    voice = _oops_voice(sr)                          # wrong arrow -> "Oops!"
    SFX['blocked'] = voice if voice is not None else _make_sound(_oops_synth(sr), 0.9)
    m = Z(0.5); _place(m, _chirp(700, 1500, 0.12, sr), 0, sr); _place(m, _chirp(900, 1900, 0.14, sr), 0.12, sr)   # hint
    SFX['hint'] = _make_sound(_norm(m), 0.5)
    SFX['wind'] = _make_sound(_whoosh(0.8, sr, 4, 200, 4500), 0.6)                                                 # wind
    m = Z(0.5)                                      # eraser: scrub scrub tick
    _place(m, _whoosh(0.09, sr, 5, 800, 6000)*0.8, 0, sr); _place(m, _whoosh(0.09, sr, 6, 800, 6000)*0.8, 0.11, sr); _place(m, _bloop(900, sr, 0.1), 0.24, sr, 0.6)
    SFX['erase'] = _make_sound(_norm(m), 0.5)
    SFX['undo'] = _make_sound(_norm(_chirp(1000, 450, 0.2, sr, 9)), 0.5)                                           # undo
    m = Z(0.6)                                      # reset: shuffle
    for k in range(3): _place(m, _whoosh(0.12, sr, 30+k, 400, 5000)*0.7, k*0.1, sr)
    _place(m, _bloop(380, sr, 0.15), 0.34, sr, 0.8)
    SFX['reset'] = _make_sound(_norm(m), 0.5)
    t = np.arange(int(sr*0.05))/sr                  # click
    SFX['click'] = _make_sound(_norm(np.sin(2*np.pi*650*t)*np.exp(-t*70)), 0.35)
    m = Z(1.6)                                      # game over: gentle falling notes (no bombs)
    for i, f in enumerate((392.0, 349.2, 311.1, 261.6)):
        tt = np.arange(int(sr*0.8))/sr; _place(m, (np.sin(2*np.pi*f*tt)+0.3*np.sin(4*np.pi*f*tt))*np.exp(-tt*3.2)*np.minimum(1, tt/0.02), i*0.24, sr)
    SFX['lose'] = _make_sound(_norm(_echo(m, sr, 0.2, 0.25, 2)), 0.45)
    a_, ev_ = _diwali(sr, False); FX_TIMELINES['win'] = ev_; SFX['win'] = _make_sound(a_, 0.9)        # level complete: short Diwali
    a_, ev_ = _diwali(sr, True); FX_TIMELINES['diwali'] = ev_; SFX['diwali'] = _make_sound(a_, 0.95)       # game finished: full Diwali show
try:
    _build_sounds()
except Exception:
    SFX = {}

def play_sfx(name):
    if not sound_on: return
    snd = SFX.get(name)
    if snd is not None:
        try: snd.play()
        except pygame.error: pass

def play_celebration(): play_sfx('win')

def buzz():
    """Vibration: screen shake (+ controller rumble if a gamepad is connected)."""
    global shake_until
    if not vibe_on: return
    shake_until = pygame.time.get_ticks()+260
    try:
        pygame.joystick.init()
        for i in range(pygame.joystick.get_count()):
            try: pygame.joystick.Joystick(i).rumble(0.7, 0.7, 250)
            except Exception: pass
    except Exception: pass

def touch():
    global last_input_ms
    last_input_ms = pygame.time.get_ticks()

def schedule(delay_ms, fn): pending.append((pygame.time.get_ticks()+delay_ms, fn))

def game_finale():
    """Game finished: Diwali crackers, bombs and rockets + fireworks on screen."""
    global finale_start
    finale_start = pygame.time.get_ticks(); play_sfx('diwali'); fx_start('diwali')

# ---- Window: everything is drawn on a fixed 1280x800 canvas and scaled to the screen (FULL SCREEN by default, F11 toggles).
try:
    import ctypes; ctypes.windll.user32.SetProcessDPIAware()      # sharp full screen on Windows even with display scaling
except Exception: pass
VW, VH = 1280, 800
OX = (VW-1000)//2            # pop-up boxes are designed on a 1000x800 sheet and centred with this offset
fullscreen_on = True
def set_display(full):
    global window, fullscreen_on
    fullscreen_on = full
    try:
        window = pygame.display.set_mode((0, 0), pygame.FULLSCREEN) if full else pygame.display.set_mode((VW, VH), pygame.RESIZABLE)
    except Exception:
        fullscreen_on = False; window = pygame.display.set_mode((VW, VH), pygame.RESIZABLE)
set_display(True)
VERSION = 'v14'
pygame.display.set_caption(f'ARROW PUZZLE {VERSION} | Python + Pygame')
print('Running', __file__, VERSION)
screen = pygame.Surface((VW, VH))
clock = pygame.time.Clock()
view_scale, view_off = 1.0, (0, 0)

def present():
    global view_scale, view_off
    win = pygame.display.get_surface(); ww, wh = win.get_size()
    view_scale = min(ww / VW, wh / VH)
    sw, sh = max(1, int(VW * view_scale)), max(1, int(VH * view_scale))
    view_off = ((ww - sw) // 2, (wh - sh) // 2)
    win.fill(THEMES[theme_index]['bg'])
    off = view_off
    if shake_until > pygame.time.get_ticks(): off = (view_off[0]+random.randint(-7, 7), view_off[1]+random.randint(-7, 7))
    if (sw, sh) == (VW, VH): win.blit(screen, off)
    else: win.blit(pygame.transform.smoothscale(screen, (sw, sh)), off)
    pygame.display.flip()

def to_virtual(pos):
    return (int((pos[0] - view_off[0]) / view_scale), int((pos[1] - view_off[1]) / view_scale))

def esc_quit():
    """ESC leaves full screen first; pressing it again in a window quits."""
    if fullscreen_on: set_display(False); return False
    return True

BOARD = pygame.Rect(265, 128, 750, 612)

# ---- Arrow style: EVERY level uses the same small arrows (like the reference game); bigger levels = bigger shapes ----
SLIDE_SPEED = 1.2   # pixels per millisecond when an arrow escapes
CLIP = BOARD.inflate(10, 6)
CELL = 26                            # distance between grid points, same on every level
MAX_COLS, MAX_ROWS = 28, 23          # biggest board that fits the screen
EXT_FRAC = 0.42                      # arrows are stretched past their end cells -> no empty gaps
LINE_W = 4; HEAD_LEN = 16; HEAD_W = 16; CORNER_R = 13.0; EXT = CELL * EXT_FRAC
COLS = ROWS = 10; ORIGIN = (0, 0); LENGTHS = [2, 3, 4]; MASK = set(); SHAPE = 'heart'

SHAPES = ['heart', 'circle', 'diamond', 'star', 'hexagon', 'triangle', 'plus', 'ring', 'moon', 'arrow']
SQUARISH = {'circle', 'ring', 'star', 'moon', 'hexagon', 'plus', 'diamond'}
SHAPE_BOOST = {'star': 1.3, 'moon': 1.2, 'plus': 1.1, 'triangle': 1.05, 'diamond': 1.1}   # thin shapes get a little more room
STAR_POLY = [(math.cos(-math.pi/2+i*math.pi/5)*(1 if i % 2 == 0 else 0.42), math.sin(-math.pi/2+i*math.pi/5)*(1 if i % 2 == 0 else 0.42)) for i in range(10)]

def _in_poly(x, y, poly):
    inside = False; j = len(poly)-1
    for i in range(len(poly)):
        xi, yi = poly[i]; xj, yj = poly[j]
        if (yi > y) != (yj > y) and x < (xj-xi)*(y-yi)/(yj-yi)+xi: inside = not inside
        j = i
    return inside

def shape_has(shape, u, v):
    """u, v in [-1, 1] (v grows downwards). True when that spot is part of the shape."""
    if shape == 'circle': return u*u+v*v <= 1
    if shape == 'ring': return 0.2 <= u*u+v*v <= 1
    if shape == 'diamond': return abs(u)+abs(v) <= 1
    if shape == 'heart':
        x = u*1.25; y = -v*1.2+0.1
        return (x*x+y*y-1)**3-x*x*y**3 <= 0
    if shape == 'star': return _in_poly(u, v, STAR_POLY)
    if shape == 'hexagon': return abs(v) <= 0.92 and abs(u)+abs(v)*0.5774 <= 1
    if shape == 'triangle': return abs(u) <= (v+1)/2
    if shape == 'plus': return abs(u) <= 0.36 or abs(v) <= 0.36
    if shape == 'moon': return u*u+v*v <= 1 and (u-0.42)**2+(v+0.05)**2 > 0.72**2
    if shape == 'arrow': return (v <= 0.1 and abs(u) <= (v+1)*0.95) or (v > 0.05 and abs(u) <= 0.3)
    return True

def build_mask(shape, cols, rows):
    m = {(c, r) for c in range(cols) for r in range(rows) if shape_has(shape, (c+0.5)/cols*2-1, (r+0.5)/rows*2-1)}
    changed = True
    while changed:                                   # drop cells that have no neighbour
        changed = False
        for c in list(m):
            if not any((c[0]+d[0], c[1]+d[1]) in m for d in DIRS): m.discard(c); changed = True
    best = set(); seen = set()                       # keep only the biggest connected piece
    for c in sorted(m):
        if c in seen: continue
        comp = {c}; stack = [c]; seen.add(c)
        while stack:
            x = stack.pop()
            for d in DIRS:
                n = (x[0]+d[0], x[1]+d[1])
                if n in m and n not in seen: seen.add(n); comp.add(n); stack.append(n)
        if len(comp) > len(best): best = comp
    return best

def lengths_for(lv):
    # many short arrows keep the board packed; deeper levels add long winding ones
    return [2,2,2,3,3,3,4,4,5,6,7] + [9,11,13]*(lv//5)

def set_grid(lv):
    """Pick the shape for this level (a different one each level) and size it to the level."""
    global COLS,ROWS,ORIGIN,LENGTHS,MASK,SHAPE
    SHAPE = SHAPES[(lv-1) % len(SHAPES)]
    sc = min(1.0, 0.62+0.055*(lv-1)); cols = max(10, int(MAX_COLS*sc)); rows = max(9, int(MAX_ROWS*sc))
    boost = SHAPE_BOOST.get(SHAPE, 1.0); cols = min(MAX_COLS, int(cols*boost)); rows = min(MAX_ROWS, int(rows*boost))
    if SHAPE in SQUARISH: cols = rows = min(cols, rows)
    mask = build_mask(SHAPE, cols, rows)
    if len(mask) < 12: mask = {(c, r) for c in range(cols) for r in range(rows)}
    mc = min(c for c, r in mask); mr = min(r for c, r in mask)
    MASK = {(c-mc, r-mr) for c, r in mask}
    COLS = max(c for c, r in MASK)+1; ROWS = max(r for c, r in MASK)+1
    ORIGIN = (BOARD.centerx-(COLS-1)*CELL/2, BOARD.centery-(ROWS-1)*CELL/2)
    LENGTHS = lengths_for(lv)

def difficulty_for(lv):
    if lv <= 2: return 'EASY', (60, 185, 110)
    if lv <= 5: return 'NORMAL', (70, 150, 240)
    if lv <= 9: return 'HARD', (240, 140, 50)
    return 'EXPERT', (225, 60, 80)

SAVE_FILE = Path('arrow_puzzle_scores.json')
THEMES = [
 {'name':'Blue','bg':(205,228,250),'panel':(5,22,42),'accent':(0,190,225),'board':(255,255,255),'arrow':(10,16,64),'dot':(190,205,225),'circle':(20,130,240)},
 {'name':'Pink','bg':(255,226,240),'panel':(46,16,40),'accent':(255,95,145),'board':(255,248,251),'arrow':(88,16,60),'dot':(240,195,215),'circle':(255,95,145)},
 {'name':'Green','bg':(220,246,228),'panel':(8,35,29),'accent':(55,205,125),'board':(250,255,251),'arrow':(8,62,40),'dot':(185,225,200),'circle':(36,180,90)},
 {'name':'Light','bg':(250,252,255),'panel':(5,22,42),'accent':(0,165,210),'board':(255,255,255),'arrow':(10,16,64),'dot':(200,205,225),'circle':(205,235,255)}]
theme_index = 3
font=pygame.font.SysFont('arial',20,bold=True); small=pygame.font.SysFont('arial',15,bold=True)
tiny=pygame.font.SysFont('arial',11,bold=True); title=pygame.font.SysFont('arial',38,bold=True)
score,lives,level=0,3,1
time_options=[30,60,90,120]; timer_choice=1; time_left=0
playing=False; game_mode='Classic'; hint_index=None; eraser_mode=False
history=[]; message='Press START to begin!'; game_start_ms=0
best_score=0; top_scores=[]; streak=0; last_daily=''; max_level=1; battle_wins=0
moving={}; flash={}; next_level_at=None
awaiting_next=False; pause_start=0; box_open_t=0
hint_until=0; game_started=False; retry_box=None; level_start_score=0; board_backup=[]; AUTO_MS=5500
COST={'hint':15,'wind':25,'eraser':20,'undo':10,'reset':20}     # points paid for every help

def lives_for(lv): return 3 if lv<=5 else 2
def charges_for(lv):
    """How many times each help can be used per level. Deeper levels give fewer helps."""
    return {'hint':1,'wind':1 if lv<=8 else 0,'eraser':1 if lv<=5 else 0,'undo':1,'reset':1}
uses=charges_for(1)

def spend(kind):
    global score
    uses[kind]=uses.get(kind,0)-1; score=max(0,score-COST[kind])

def snapshot_level():
    global board_backup,level_start_score
    level_start_score=score
    board_backup=[dict(c,points=list(c['points']),cells=list(c['cells']),removed=False) for c in board]

def begin_level():
    global uses
    uses=charges_for(level); snapshot_level(); save_progress()

def saved_start(mode=None):
    """(level, score) saved for this mode - (1, 0) when there is nothing to continue."""
    p=progress.get(mode or game_mode)
    try:
        if isinstance(p,dict) and int(p.get('level',1))>1: return int(p['level']),int(p.get('score',0))
    except Exception: pass
    return 1,0

def save_progress():
    """Remember the level so closing the game never throws the levels away."""
    if not game_started or battle() or game_mode=='Daily Challenge': return
    progress[game_mode]={'level':level,'score':level_start_score}; save_data()
# Friends Battle state
turn=0; bs=[0,0]; bl=[3,3]
MODES=['Classic','Time Challenge','Daily Challenge','Friends Battle']

DIR_VECTORS={'right':(1,0),'left':(-1,0),'up':(0,-1),'down':(0,1)}
VEC_TO_DIR={v:k for k,v in DIR_VECTORS.items()}
DIRS=list(DIR_VECTORS.values())

def load_data():
    global best_score, top_scores, streak, last_daily, net_server_text, max_level, battle_wins, progress, sound_on, vibe_on, autolock_on, theme_index, timer_choice
    try:
        d=json.loads(SAVE_FILE.read_text())
        best_score=int(d.get('best',0)); top_scores=d.get('top',[]); streak=int(d.get('streak',0)); last_daily=d.get('last_daily',''); daily_done.update(d.get('daily_done',[])); net_server_text=d.get('server',net_server_text); max_level=int(d.get('max_level',1)); battle_wins=int(d.get('battle_wins',0))
        progress=d.get('progress',{}) if isinstance(d.get('progress',{}),dict) else {}
        sound_on=bool(d.get('sound',True)); vibe_on=bool(d.get('vibration',True)); autolock_on=bool(d.get('autolock',False))
        theme_index=int(d.get('theme',theme_index))%len(THEMES); timer_choice=int(d.get('timer',timer_choice))%len(time_options)
    except Exception: pass

def save_data():
    try: SAVE_FILE.write_text(json.dumps({'best':best_score,'top':top_scores[:5],'streak':streak,'last_daily':last_daily,'daily_done':sorted(daily_done),'server':net_server_text,'max_level':max_level,'battle_wins':battle_wins,
                                          'progress':progress,'sound':sound_on,'vibration':vibe_on,'autolock':autolock_on,'theme':theme_index,'timer':timer_choice}))
    except Exception: pass

def say(s):
    global message
    message=s

def rounded(rect,color,r=14,border=None,bw=0):
    pygame.draw.rect(screen,color,rect,border_radius=r)
    if border: pygame.draw.rect(screen,border,rect,bw,border_radius=r)

def txt(s,x,y,f=small,color=(255,255,255),center=False):
    surf=f.render(str(s),True,color); r=surf.get_rect()
    if center:r.center=(int(x),int(y))
    else:r.topleft=(int(x),int(y))
    screen.blit(surf,r)

def buttons():
    return {
      'online':pygame.Rect(1030,582,235,48),'back':pygame.Rect(15,66,235,48),'start':pygame.Rect(265,66,125,48),'hint':pygame.Rect(400,66,92,48),'wind':pygame.Rect(502,66,92,48),
      'eraser':pygame.Rect(604,66,92,48),'undo':pygame.Rect(706,66,92,48),'reset':pygame.Rect(808,66,92,48),
      'theme':pygame.Rect(1045,230,205,35),'timer30':pygame.Rect(1045,318,44,30),'timer60':pygame.Rect(1097,318,44,30),
      'timer90':pygame.Rect(1149,318,44,30),'timer120':pygame.Rect(1201,318,44,30),
      'leftmode':pygame.Rect(24,574,35,35),'rightmode':pygame.Rect(206,574,35,35),
      **{f'mode{i}':pygame.Rect(1045,410+i*38,205,32) for i in range(4)}}

LABEL_F = pygame.font.SysFont('arial',13,bold=True)

def _arc_pts(cx,cy,r,a0,a1,n=16):
    return [(cx+r*math.cos(a0+(a1-a0)*i/n), cy+r*math.sin(a0+(a1-a0)*i/n)) for i in range(n+1)]

def _arrowhead(col,px,py,tx,ty,size=6):
    l=math.hypot(tx,ty) or 1; tx,ty=tx/l,ty/l; nx,ny=-ty,tx
    pygame.draw.polygon(screen,col,[(px+tx*size,py+ty*size),(px+nx*size*0.95,py+ny*size*0.95),(px-nx*size*0.95,py-ny*size*0.95)])

def _stroke(col,pts,w=2):
    ip=[(int(round(x)),int(round(y))) for x,y in pts]
    pygame.draw.lines(screen,col,False,ip,w)

def draw_icon(name,cx,cy):
    W=(255,255,255)
    if name=='play':
        pygame.draw.polygon(screen,W,[(cx-7,cy-9),(cx-7,cy+9),(cx+9,cy)])
    elif name=='online':                                 # globe
        pygame.draw.circle(screen,W,(cx,cy),11,2); pygame.draw.ellipse(screen,W,pygame.Rect(cx-5,cy-11,10,22),2)
        pygame.draw.line(screen,W,(cx-11,cy),(cx+11,cy),2); pygame.draw.line(screen,W,(cx-8,cy-6),(cx+8,cy-6),1); pygame.draw.line(screen,W,(cx-8,cy+6),(cx+8,cy+6),1)
    elif name=='hint':                                   # light bulb
        pygame.draw.circle(screen,(255,226,90),(cx,cy-3),8); pygame.draw.circle(screen,(255,248,200),(cx-3,cy-6),3)
        pygame.draw.rect(screen,(225,225,235),(cx-4,cy+5,8,4)); pygame.draw.rect(screen,(170,175,190),(cx-3,cy+9,6,3))
        for ang in (-90,-45,-135,-8,-172):
            r=math.radians(ang); _stroke((255,236,140),[(cx+12*math.cos(r),cy-3+12*math.sin(r)),(cx+16*math.cos(r),cy-3+16*math.sin(r))])
    elif name=='wind':                                   # swirling wind lines
        _stroke(W,[(cx-12,cy-7),(cx+3,cy-7)]+_arc_pts(cx+3,cy-10,3,math.pi/2,-math.pi,8))
        _stroke(W,[(cx-12,cy),(cx+9,cy)]+_arc_pts(cx+9,cy+3,3,-math.pi/2,math.pi,8))
        _stroke(W,[(cx-12,cy+7),(cx+1,cy+7)])
    elif name=='eraser':                                 # tilted rubber eraser
        A=-0.55; ca,sa=math.cos(A),math.sin(A)
        def rot(u,v): return (cx+u*ca-v*sa, cy+u*sa+v*ca)
        pygame.draw.polygon(screen,(235,240,252),[rot(-12,-6),rot(2,-6),rot(2,6),rot(-12,6)])
        pygame.draw.polygon(screen,(255,150,170),[rot(2,-6),rot(12,-6),rot(12,6),rot(2,6)])
        pygame.draw.polygon(screen,(40,50,90),[rot(-12,-6),rot(12,-6),rot(12,6),rot(-12,6)],1)
    elif name=='undo':                                   # curved arrow pointing back
        pts=_arc_pts(cx+1,cy+3,8,0.9,-2.0,16); _stroke(W,pts,3)
        px,py=pts[-1]; _arrowhead(W,px,py,math.sin(-2.0),-math.cos(-2.0),7)
    elif name=='reset':                                  # circular refresh arrow
        pts=_arc_pts(cx,cy,8,-0.5,4.5,20); _stroke(W,pts,3)
        px,py=pts[-1]; _arrowhead(W,px,py,-math.sin(4.5),math.cos(4.5),7)

def button(rect,label,color,enabled=True,f=small,icon=None):
    c=color if enabled else (90,105,120)
    rounded(rect,c,10,(0,0,0),2)
    if icon=='play':
        draw_icon('play',rect.x+34,rect.centery); txt(label,rect.centerx+16,rect.centery,f,(255,255,255),True)
    elif icon:
        draw_icon(icon,rect.centerx,rect.y+18); txt(label,rect.centerx,rect.bottom-10,LABEL_F,(255,255,255),True)
    else: txt(label,*rect.center,f,(255,255,255),True)

def badge(rect,n):
    c=(rect.right-11,rect.y+11); col=(30,40,80) if n>0 else (200,50,60)
    pygame.draw.circle(screen,(255,255,255),c,10); pygame.draw.circle(screen,col,c,10,2); txt(n,c[0],c[1],tiny,col,True)

def point_distance_to_segment(p,a,b):
    px,py=p; ax,ay=a; bx,by=b; dx=bx-ax; dy=by-ay
    if dx==dy==0:return math.hypot(px-ax,py-ay)
    t=max(0,min(1,((px-ax)*dx+(py-ay)*dy)/(dx*dx+dy*dy)))
    return math.hypot(px-(ax+t*dx),py-(ay+t*dy))

# ---------------------------------------------------------------
#  Board generation: EVERY grid cell is covered, always solvable
# ---------------------------------------------------------------

def cell_to_px(c):
    return (ORIGIN[0]+c[0]*CELL, ORIGIN[1]+c[1]*CELL)

def inb(c): return c in MASK

def compress(cells):
    pts=[cells[0]]
    for i in range(1,len(cells)-1):
        a,b,c=cells[i-1],cells[i],cells[i+1]
        if (b[0]-a[0],b[1]-a[1])!=(c[0]-b[0],c[1]-b[1]): pts.append(b)
    pts.append(cells[-1])
    px=[cell_to_px(p) for p in pts]
    # stretch both ends so arrows fill the gaps between neighbours
    (ax,ay),(bx,by)=px[0],px[1]; l=math.hypot(bx-ax,by-ay) or 1
    px[0]=(ax-(bx-ax)/l*EXT,ay-(by-ay)/l*EXT)
    (ax,ay),(bx,by)=px[-2],px[-1]; l=math.hypot(bx-ax,by-ay) or 1
    px[-1]=(bx+(bx-ax)/l*EXT,by+(by-ay)/l*EXT)
    return px

def make_partition(rng):
    """Split the whole grid into winding paths (each >= 2 cells)."""
    order=sorted(MASK); rng.shuffle(order)
    paths=[]; owner={}; singles=[]
    for start in order:
        if start in owner: continue
        target=rng.choice(LENGTHS); cells=[start]; used={start}; d=rng.choice(DIRS)
        while len(cells)<target:
            cand=DIRS[:]; rng.shuffle(cand)
            if rng.random()<0.4 and d in cand: cand.remove(d); cand.insert(0,d)
            for nd in cand:
                n=(cells[-1][0]+nd[0],cells[-1][1]+nd[1])
                if inb(n) and n not in owner and n not in used:
                    cells.append(n); used.add(n); d=nd; break
            else: break
        if len(cells)>=2:
            for c in cells: owner[c]=len(paths)
            paths.append(cells)
        else: singles.append(start)
    # leftover single cells: glue them onto a neighbouring path
    for c in singles:
        done=False
        for dd in DIRS:
            n=(c[0]+dd[0],c[1]+dd[1]); p=owner.get(n)
            if p is None: continue
            if paths[p][0]==n: paths[p].insert(0,c); owner[c]=p; done=True; break
            if paths[p][-1]==n: paths[p].append(c); owner[c]=p; done=True; break
        if done: continue
        for dd in DIRS:
            n=(c[0]+dd[0],c[1]+dd[1]); p=owner.get(n)
            if p is None: continue
            path=paths[p]; i=path.index(n)
            if i>=2: P1=path[:i]; P2=[c]+path[i:]
            elif len(path)-i-1>=2: P1=path[:i+1]+[c]; P2=path[i+1:]
            else: continue
            paths[p]=P1; paths.append(P2); q=len(paths)-1
            for cc in P1: owner[cc]=p
            for cc in P2: owner[cc]=q
            done=True; break
        if not done: return None
    return paths

def orient_paths(paths,rng):
    """Peel the puzzle like an onion to choose which end of each path is the arrowhead.
    Each arrow is picked only when its exit line is clear, so the result is solvable."""
    occ={}
    for i,p in enumerate(paths):
        for c in p: occ[c]=i
    remaining=set(range(len(paths))); result={}
    while remaining:
        cands=[]
        for i in remaining:
            for cells in (paths[i],paths[i][::-1]):
                d=(cells[-1][0]-cells[-2][0],cells[-1][1]-cells[-2][1])
                x,y=cells[-1][0]+d[0],cells[-1][1]+d[1]; clear=True
                while 0<=x<COLS and 0<=y<ROWS:
                    if (x,y) in occ: clear=False; break
                    x+=d[0]; y+=d[1]
                if clear: cands.append((i,cells,d))
        if not cands: return None
        i,cells,d=rng.choice(cands)
        result[i]=(cells,d); remaining.discard(i)
        for c in paths[i]: occ.pop(c,None)
    return [{'cells':result[i][0],'points':compress(result[i][0]),'dir':VEC_TO_DIR[result[i][1]],'removed':False} for i in sorted(result)]

def free_count(arrows):
    occ={c for a in arrows for c in a['cells']}; n=0
    for a in arrows:
        d=DIR_VECTORS[a['dir']]; x,y=a['cells'][-1][0]+d[0],a['cells'][-1][1]+d[1]; ok=True
        while 0<=x<COLS and 0<=y<ROWS:
            if (x,y) in occ: ok=False; break
            x+=d[0]; y+=d[1]
        n+=ok
    return n

def waves(arrows):
    """How many rounds are needed if you always remove every free arrow at once (more rounds = harder chains)."""
    occ={}
    for i,a in enumerate(arrows):
        for c in a['cells']: occ[c]=i
    remaining=set(range(len(arrows))); w=0
    while remaining:
        free=[]
        for i in remaining:
            d=DIR_VECTORS[arrows[i]['dir']]; x,y=arrows[i]['cells'][-1][0]+d[0],arrows[i]['cells'][-1][1]+d[1]; ok=True
            while 0<=x<COLS and 0<=y<ROWS:
                if (x,y) in occ: ok=False; break
                x+=d[0]; y+=d[1]
            if ok: free.append(i)
        if not free: return 99
        for i in free:
            remaining.discard(i)
            for c in arrows[i]['cells']: occ.pop(c,None)
        w+=1
    return w

def make_board(seed=None,lv=1):
    """Tough boards: plenty of arrows, few free at the start and long chains of 'this blocks that'."""
    set_grid(lv); rng=random.Random(seed)
    tries=min(20,4+2*lv); best=None; bestk=(True,0,10**9)
    attempts=0
    while attempts<tries*40 or (best is None and attempts<6000):
        attempts+=1
        paths=make_partition(rng)
        if paths is None: continue
        arrows=orient_paths(paths,rng)
        if not arrows: continue
        k=(len(arrows)<len(MASK)/(3.5+0.08*lv), -waves(arrows), free_count(arrows)/len(arrows))
        if k<bestk: best,bestk=arrows,k
        tries-=1
        if tries<=0: break
    return best or []

def new_board():
    seed=int((daily_date or datetime.date.today()).strftime('%Y%m%d'))*100+level if game_mode=='Daily Challenge' else None
    b=make_board(seed,level)
    return b if b else make_board(None,level)

board=[]
def path_segments(cell): return list(zip(cell['points'][:-1],cell['points'][1:]))

def is_safe(index):
    """Free when the straight line in front of the arrowhead hits no other arrow."""
    if index>=len(board) or board[index]['removed']: return False
    me=board[index]; blocked=set()
    for j,o in enumerate(board):
        if j!=index and not o['removed']: blocked.update(o['cells'])
    dx,dy=DIR_VECTORS[me['dir']]; x,y=me['cells'][-1]; x+=dx; y+=dy
    while 0<=x<COLS and 0<=y<ROWS:
        if (x,y) in blocked: return False
        x+=dx; y+=dy
    return True

def safe_index(): return next((i for i in range(len(board)) if is_safe(i)),None)

# ---------------------------------------------------------------
#  Game state helpers
# ---------------------------------------------------------------
def battle(): return game_mode=='Friends Battle'
def race(): return game_mode=='Friends Battle' and online_on()      # online = everybody races on the SAME puzzle
def hotseat(): return battle() and not race()                       # offline Friends Battle = take turns

def store_turn():
    bs[turn]=score; bl[turn]=lives

def switch_turn():
    global score,lives,turn
    store_turn(); turn=1-turn; score=bs[turn]; lives=bl[turn]

def remember():
    store_turn()
    history.append({'board':[dict(c,points=list(c['points'])) for c in board],'score':score,'lives':lives,'level':level,
                    'time_left':time_left,'turn':turn,'bs':bs[:],'bl':bl[:]})
    if len(history)>30:history.pop(0)

def update_best():
    global best_score
    if not battle() and score>best_score: best_score=score; save_data()

def record_score():
    global top_scores,best_score
    if battle(): return
    best_score=max(best_score,score)
    top_scores=sorted(set(top_scores+[score]),reverse=True)[:5]; save_data()

def update_streak():
    global streak,last_daily
    today=datetime.date.today(); d=daily_date or today; daily_done.add(d.isoformat())
    if d!=today or last_daily==today.isoformat(): save_data(); return      # old days count as done, but only today feeds the streak
    streak=streak+1 if last_daily==(today-datetime.timedelta(days=1)).isoformat() else 1
    last_daily=today.isoformat(); save_data()

def start_game(given_board=None, fresh=False):
    """Starts the game - continues from the saved level unless fresh=True (then level 1)."""
    global board,score,lives,level,time_left,playing,history,hint_index,eraser_mode,game_start_ms,moving,flash,next_level_at,turn,bs,bl,awaiting_next,combo,game_started,retry_box,race_start,race_result,opp_left,opp_lives,opp_out,me_out
    race_start=0; race_result=None; opp_left=0; opp_lives=3; opp_out=False; me_out=False
    if fresh: progress.pop(game_mode,None)
    lv0,sc0=(1,0) if (given_board or battle()) else saved_start()
    combo=0; pending.clear(); fx_stop(); play_sfx('click'); awaiting_next=False; retry_box=None; score,level=sc0,lv0; lives=lives_for(lv0); playing=True; game_started=True; turn=0; bs=[0,0]; bl=[3,3]
    history=[];hint_index=None;eraser_mode=False;moving={};flash={};next_level_at=None
    game_start_ms=pygame.time.get_ticks()
    time_left=time_options[timer_choice] if game_mode=='Time Challenge' else 0
    board=given_board if given_board else new_board(); begin_level(); show_intro()
    say('P1 starts! Pick a free arrow.' if battle() else 'Find an arrow with a clear path to the edge!')
    if lv0>1 and not battle(): say(f'WELCOME BACK! Continuing from LEVEL {lv0}')

def retry_level():
    """Out of lives / time up: replay the SAME level (never go back to level 1)."""
    global board,score,lives,time_left,playing,history,hint_index,eraser_mode,game_start_ms,moving,flash,next_level_at,awaiting_next,combo,retry_box,uses,turn,bs,bl
    combo=0; pending.clear(); fx_stop(); play_sfx('click'); awaiting_next=False; retry_box=None; next_level_at=None
    score=level_start_score; lives=lives_for(level); playing=True; history=[]; hint_index=None; eraser_mode=False; moving={}; flash={}
    board=[dict(c,points=list(c['points']),cells=list(c['cells']),removed=False) for c in board_backup]
    uses=charges_for(level); game_start_ms=pygame.time.get_ticks(); turn=0; bs=[0,0]; bl=[lives,lives]
    time_left=time_options[timer_choice] if game_mode=='Time Challenge' else 0
    show_intro(); say(f'LEVEL {level} - try again!')

def on_start():
    if online_on():
        if online_role=='host':
            if playing and race_result is None: say('Race in progress - solve the puzzle first!')
            else: host_start_online()
        else: say('Only the host can start a new round.')
        return
    if online_state in ('waiting','connecting'): say('Waiting for your friend to join...'); return
    if game_started: retry_level()
    else: start_game()

def show_retry(title):
    global retry_box
    retry_box=title

def _change_mode_fresh(m):
    global combo,level,awaiting_next,game_mode,playing,board,history,moving,flash,hint_index,eraser_mode,time_left,next_level_at,game_started,retry_box,score,intro_box
    if online_state in ('connected','waiting','connecting'): say('Leave the online room first (ONLINE button).'); return
    intro_box=False; play_sfx('click'); combo=0; level=1; awaiting_next=False; game_mode=m; playing=False; history=[]; moving={}; flash={}; hint_index=None; eraser_mode=False; next_level_at=None
    time_left=time_options[timer_choice] if m=='Time Challenge' else 0
    board=new_board(); game_started=False; retry_box=None; fx_stop(); score=0; begin_level()
    hints={'Classic':'no time limit','Time Challenge':'beat the clock','Daily Challenge':'same puzzle for everyone today','Friends Battle':'2 players, take turns'}
    say(f'MODE: {m} ({hints[m]}) - press START')


# Keep an independent paused session for Classic while other modes are open.
classic_session = None
CLASSIC_FIELDS = (
    'board', 'score', 'lives', 'level', 'time_left', 'playing', 'history',
    'hint_index', 'eraser_mode', 'moving', 'flash', 'next_level_at',
    'awaiting_next', 'pause_start', 'box_open_t', 'hint_until', 'game_started',
    'retry_box', 'level_start_score', 'board_backup', 'uses', 'combo',
    'game_start_ms', 'turn', 'bs', 'bl', 'message', 'intro_box', 'intro_open_t'
)

def change_mode(m):
    global classic_session
    if online_state in ('connected', 'waiting', 'connecting'):
        say('Leave the online room first (ONLINE button).')
        return
    if m == game_mode:
        return
    import copy
    now = pygame.time.get_ticks()
    if game_mode == 'Classic':
        classic_session = {
            'state': copy.deepcopy({key: globals()[key] for key in CLASSIC_FIELDS}),
            'paused_at': now,
            'pending': [(max(0, due-now), fn) for due, fn in pending],
        }
    pending.clear()
    _change_mode_fresh(m)
    if m != 'Classic' or classic_session is None:
        return
    saved = copy.deepcopy(classic_session['state'])
    delta = pygame.time.get_ticks() - classic_session['paused_at']
    for key in ('game_start_ms', 'pause_start', 'box_open_t', 'intro_open_t'):
        saved[key] += delta
    for key in ('next_level_at', 'hint_until'):
        if saved[key]:
            saved[key] += delta
    for key in ('moving', 'flash'):
        saved[key] = {idx: tick+delta for idx, tick in saved[key].items()}
    globals().update(saved)
    set_grid(level)
    pending.extend((pygame.time.get_ticks()+delay, fn)
                   for delay, fn in classic_session['pending'])
    fx_stop()
    say(f'CLASSIC resumed - LEVEL {level}' if game_started
        else 'MODE: Classic (no time limit) - press START')


def do_hint():
    global hint_index,hint_until
    if uses.get('hint',0)<=0: say('No hints left on this level!'); play_sfx('click'); return
    idx=safe_index()
    if idx is None: say('No clear path to hint.'); return
    spend('hint'); hint_index=idx; hint_until=pygame.time.get_ticks()+2000; play_sfx('hint')
    say(f"Hint used (-{COST['hint']} pts), {uses['hint']} left. It fades in 2s!")

def do_wind():
    if uses.get('wind',0)<=0: say('WIND already used on this level!'); play_sfx('click'); return
    idx=safe_index()
    if idx is None: say('No clear path for WIND.'); return
    remember(); spend('wind'); escape_arrow(idx,'wind'); say(f"WIND used (-{COST['wind']} pts)"); after_move()

def do_eraser():
    global eraser_mode
    if uses.get('eraser',0)<=0: say('ERASER already used on this level!'); play_sfx('click'); return
    eraser_mode=not eraser_mode; play_sfx('click')
    say(f"ERASER ON: tap any arrow (-{COST['eraser']} pts)" if eraser_mode else 'ERASER OFF')

def do_undo():
    global board,score,lives,level,time_left,turn,bs,bl,hint_index,moving,next_level_at
    if not history: return
    if uses.get('undo',0)<=0: say('No undos left on this level!'); play_sfx('click'); return
    old=history.pop(); board=old['board']; level=old['level']; time_left=old['time_left']; turn=old['turn']; bs=old['bs']; bl=old['bl']
    score=bs[turn]; lives=bl[turn]; hint_index=None; moving={}; next_level_at=None
    spend('undo'); play_sfx('undo'); say(f"LAST MOVE UNDONE (-{COST['undo']} pts)")

def do_reset():
    global board,history,hint_index,eraser_mode,moving,board_backup
    if uses.get('reset',0)<=0: say('RESET already used on this level!'); play_sfx('click'); return
    spend('reset'); play_sfx('reset'); board=new_board(); history=[]; hint_index=None; eraser_mode=False; moving={}
    board_backup=[dict(c,points=list(c['points']),cells=list(c['cells']),removed=False) for c in board]
    say(f"NEW PUZZLE (-{COST['reset']} pts)")

def escape_arrow(index,snd='pluck0'):
    cell=board[index]; cell['removed']=True; moving[index]=pygame.time.get_ticks(); play_sfx(snd)

def close_daily_complete():
    global daily_complete,page
    daily_complete=False; fx_stop(); page='daily'; play_sfx('click')

def show_daily_complete():
    global daily_complete,daily_open_t
    daily_complete=True; daily_open_t=pygame.time.get_ticks()

def after_move():
    global board,level,score,hint_index,eraser_mode,playing,next_level_at
    hint_index=None; eraser_mode=False
    if all(c['removed'] for c in board):
        if race(): race_finished_local(); return
        if battle():
            store_turn(); playing=False; game_finale()
            say('P1 WINS!' if bs[0]>bs[1] else 'P2 WINS!' if bs[1]>bs[0] else "IT'S A DRAW!")
            return
        score+=50
        if game_mode=='Daily Challenge':
            playing=False; update_streak(); record_score(); game_finale(); say('DAILY CHALLENGE COMPLETE! +50 BONUS'); schedule(900,show_daily_complete)
        else:
            play_sfx('win'); fx_start('win'); next_level_at=pygame.time.get_ticks()+800; say(f'LEVEL {level} CLEARED! +50 BONUS')
    elif safe_index() is None: say('No clear arrow. Use WIND, ERASER or RESET.')
    update_best()

def tap_arrow(index):
    global score,lives,hint_index,eraser_mode,playing,combo
    if not playing or board[index]['removed']:return
    if eraser_mode:
        remember();board[index]['removed']=True;spend('eraser');play_sfx('erase');say(f"ERASER USED (-{COST['eraser']} pts)");after_move();return
    if is_safe(index):
        combo+=1; remember();escape_arrow(index,f'pluck{min(combo-1,9)}');score+=10;hint_index=None
        say('ARROW ESCAPED! +10 POINTS')
        if hotseat() and not all(c['removed'] for c in board):
            switch_turn(); say(f'ARROW ESCAPED! P{turn+1}, your turn')
        after_move()
    else:
        combo=0;lives-=1;hint_index=None;flash[index]=pygame.time.get_ticks(); buzz()
        if lives<=0:
            playing=False; play_sfx('blocked')
            if race(): race_out()
            elif battle():
                store_turn(); say(f'P{turn+1} IS OUT OF LIVES - P{2-turn} WINS!'); schedule(900,game_finale)
            else:
                record_score(); say(f'OUT OF LIVES! Level {level} will restart - not level 1')
                schedule(800,lambda:(play_sfx('lose'),show_retry('OUT OF LIVES!')))
        else:
            play_sfx('blocked'); say('BLOCKED PATH! Try another arrow.')
            if hotseat(): switch_turn(); say(f'BLOCKED! P{turn+1}, your turn')

# ---------------------------------------------------------------
#  Arrow drawing: thick line, rounded corners, solid head
# ---------------------------------------------------------------
def rounded_path(pts,radius,steps=8):
    if len(pts)<3: return [(float(x),float(y)) for x,y in pts]
    out=[tuple(map(float,pts[0]))]
    for i in range(1,len(pts)-1):
        p0,p1,p2=pts[i-1],pts[i],pts[i+1]
        v1=(p0[0]-p1[0],p0[1]-p1[1]); v2=(p2[0]-p1[0],p2[1]-p1[1])
        l1,l2=math.hypot(*v1),math.hypot(*v2)
        if l1==0 or l2==0: continue
        r=min(radius,l1/2,l2/2)
        a=(p1[0]+v1[0]/l1*r,p1[1]+v1[1]/l1*r); b=(p1[0]+v2[0]/l2*r,p1[1]+v2[1]/l2*r)
        for s in range(steps+1):
            t=s/steps
            out.append(((1-t)**2*a[0]+2*(1-t)*t*p1[0]+t**2*b[0],(1-t)**2*a[1]+2*(1-t)*t*p1[1]+t**2*b[1]))
    out.append(tuple(map(float,pts[-1])))
    return out

def draw_arrow_core(line,tip,ux,uy,color):
    width,head,head_w=LINE_W,HEAD_LEN,HEAD_W
    ipts=[(int(round(x)),int(round(y))) for x,y in rounded_path(line,CORNER_R)]
    if len(ipts)>=2: pygame.draw.lines(screen,color,False,ipts,width)
    for p in ipts: pygame.draw.circle(screen,color,p,width//2)
    bx,by=tip[0]-ux*head,tip[1]-uy*head; px,py=-uy*head_w/2,ux*head_w/2
    pygame.draw.polygon(screen,color,[(int(tip[0]),int(tip[1])),(int(bx+px),int(by+py)),(int(bx-px),int(by-py))])

def draw_arrow(points,color):
    if len(points)<2:return
    (x1,y1),(x2,y2)=points[-2],points[-1]
    length=math.hypot(x2-x1,y2-y1) or 1; ux,uy=(x2-x1)/length,(y2-y1)/length
    base=(x2-ux*HEAD_LEN,y2-uy*HEAD_LEN)
    draw_arrow_core(list(points[:-1])+[base],(x2,y2),ux,uy,color)

def sub_polyline(pts,s0,s1):
    """Part of a polyline between arc-lengths s0 and s1."""
    out=[]
    def add(p):
        if not out or math.hypot(p[0]-out[-1][0],p[1]-out[-1][1])>0.01: out.append(p)
    cum=0
    for k in range(len(pts)-1):
        a,b=pts[k],pts[k+1]; seg=math.hypot(b[0]-a[0],b[1]-a[1])
        if seg==0: continue
        lo,hi=cum,cum+seg; ta,tb=max(s0,lo),min(s1,hi)
        if ta<=tb:
            add((a[0]+(b[0]-a[0])*(ta-lo)/seg,a[1]+(b[1]-a[1])*(ta-lo)/seg))
            add((a[0]+(b[0]-a[0])*(tb-lo)/seg,a[1]+(b[1]-a[1])*(tb-lo)/seg))
        cum=hi
    return out

def draw_sliding_arrow(cell,age,color):
    """The arrow slides along its own shape and leaves straight out of its head."""
    pts=cell['points']; dx,dy=DIR_VECTORS[cell['dir']]; hx,hy=pts[-1]
    L=sum(math.hypot(b[0]-a[0],b[1]-a[1]) for a,b in zip(pts[:-1],pts[1:]))
    edge={'right':CLIP.right-hx,'left':hx-CLIP.left,'down':CLIP.bottom-hy,'up':hy-CLIP.top}[cell['dir']]
    s=age*SLIDE_SPEED
    if s>=L+edge+4: return False
    ext=list(pts)+[(hx+dx*(edge+L+40),hy+dy*(edge+L+40))]
    line=sub_polyline(ext,s,L+s-HEAD_LEN)
    if len(line)<2: return True
    draw_arrow_core(line,(hx+dx*s,hy+dy*s),dx,dy,color)
    return True

def draw_grid_dots(color):
    for (c,r) in MASK:
        x,y=cell_to_px((c,r)); pygame.draw.circle(screen,color,(int(x),int(y)),2)

def draw():
    if page!='game': draw_pages(); return
    t=THEMES[theme_index]; acc=t['accent']; panel=t['panel']; screen.fill(t['bg']); b=buttons()
    dname,dcol=difficulty_for(level); left=sum(1 for c in board if not c['removed'])
    rounded(pygame.Rect(265,16,120,36),panel,16,acc,2)
    pygame.draw.polygon(screen,(255,255,255),[(279,43),(294,28),(290,26),(301,25),(300,36),(297,32),(283,46)]); txt(left,350,34,font,(255,255,255),True)
    rounded(pygame.Rect(895,16,120,36),dcol,16,(0,0,0),2); txt(dname,955,34,small,(255,255,255),True)
    txt('ARROW',565,24,title,(230,157,44),True);txt('PUZZLE',725,24,title,(0,160,195),True)
    txt(f'{VERSION}  |  F11 = full screen',640,54,tiny,(0,105,135),True)
    can=lambda k: playing and uses.get(k,0)>0
    button(b['start'],'START' if not game_started else f'RETRY L{level}',(16,155,75),icon='play');button(b['hint'],'HINT',(0,125,205),can('hint'),icon='hint')
    button(b['wind'],'WIND',(25,100,215),can('wind'),icon='wind');button(b['eraser'],'ERASER',(222,100,52) if not eraser_mode else (255,150,40),can('eraser'),icon='eraser')
    button(b['undo'],'UNDO',(0,110,145),can('undo') and bool(history),icon='undo');button(b['reset'],'RESET',(170,40,50),can('reset'),icon='reset')
    for k in ('hint','wind','eraser','undo','reset'): badge(b[k],uses.get(k,0))
    button(b['back'],'‹  MENU',(60,80,120))
    if online_on(): draw_race_hud()
    elif online_state=='waiting': txt(f'Room {online_code} open - waiting for friend',20,490,tiny,(40,150,80))
    # left column
    rounded(pygame.Rect(15,128,235,340),panel,20,acc,2)
    txt('♥ LIVES'+(f'  (P{turn+1})' if hotseat() else ''),35,145,font,acc);txt('♥ '*lives if lives else '—',38,178,font,(245,65,90))
    pygame.draw.line(screen,acc,(30,218),(235,218),2);txt('SCORE',35,234,font,(237,174,70));txt(score,62,264,title,(242,190,80))
    if hotseat():
        sc=bs[:]; sc[turn]=score; txt(f'P1:{sc[0]}  P2:{sc[1]}',120,238,small,(255,255,255))
    pygame.draw.line(screen,acc,(30,310),(235,310),2);txt('LEVEL',35,326,font,(70,205,125));txt(level,62,357,title,(70,205,125))
    pygame.draw.line(screen,acc,(30,403),(235,403),2);txt('TIME'+(' LEFT' if game_mode=='Time Challenge' else ''),35,416,font,acc);txt(f'{time_left}s',62,440,font,(255,255,255))
    # board
    rounded(CLIP,t['board'],24,t['board'],0)
    draw_grid_dots(t['dot'])
    now=pygame.time.get_ticks()
    for i,cell in enumerate(board):
        if cell['removed']: continue
        col=t['arrow']
        if i==hint_index and now<hint_until: col=(230,155,30)
        if i in flash and now-flash[i]<400: col=(225,40,55)
        draw_arrow(cell['points'],col)
    screen.set_clip(CLIP)
    for i in list(moving):
        if not draw_sliding_arrow(board[i],now-moving[i],t['arrow']): moving.pop(i,None)
    screen.set_clip(None)
    rounded(pygame.Rect(265,748,750,40),panel,20,acc,2);txt(message[:80],640,768,small,(255,220,100) if message.startswith('Hint') else (255,255,255),True)
    if daily_complete: _dim(150); fx_draw(); draw_modal(draw_daily_box)
    elif awaiting_next: _dim(150); fx_draw(); draw_modal(draw_level_box)
    elif retry_box: _dim(160); draw_modal(draw_retry_box)
    elif race_result: _dim(110); fx_draw(); draw_modal(draw_race_box)
    else: fx_draw()
    draw_race_overlay()
    if intro_box: draw_modal(draw_intro_box)
    if online_modal: _dim(170); draw_modal(draw_online_box)
    present()

BTN_NEXT = pygame.Rect(370, 478, 260, 56)
bigfont = pygame.font.SysFont('arial', 30, bold=True)
CONFETTI = [(255,95,145),(255,200,50),(60,200,120),(0,170,230),(160,100,240),(255,140,40)]

def _star_pts(cx,cy,r,rot=-math.pi/2,spikes=5,inner=0.45):
    return [(cx+(r if i%2==0 else r*inner)*math.cos(rot+i*math.pi/spikes),cy+(r if i%2==0 else r*inner)*math.sin(rot+i*math.pi/spikes)) for i in range(spikes*2)]

# ---------------- real lighting: additive glow, sparks with trails, flashes ----------------
FX_PALETTE=[(255,205,90),(255,90,90),(90,255,150),(110,205,255),(255,120,255),(255,255,255),(255,160,60)]
GLOWS={}; FX_LAYER=None; TR_LAYER=None
fx_t0=0; fx_last=0; fx_events=[]; fx_rockets=[]; fx_sparks=[]; fx_glows=[]; fx_flash=0.0

def glow_sprite(radius,color):
    key=(radius,color)
    if key not in GLOWS:
        sp=pygame.Surface((radius*2,radius*2)); sp.fill((0,0,0))
        for r in range(radius,0,-max(1,radius//40)):
            k=(1-r/radius)**2.2
            pygame.draw.circle(sp,(int(color[0]*k),int(color[1]*k),int(color[2]*k)),(radius,radius),r)
        GLOWS[key]=sp
    return GLOWS[key]

def _tier(col,k):
    m=1.0 if k>0.6 else 0.55 if k>0.3 else 0.25
    return (int(col[0]*m),int(col[1]*m),int(col[2]*m))

def fx_stop():
    global fx_events,fx_rockets,fx_sparks,fx_glows,fx_flash
    fx_events=[]; fx_rockets=[]; fx_sparks=[]; fx_glows=[]; fx_flash=0.0

def fx_start(kind):
    global fx_t0,fx_last,fx_events,fx_rockets,fx_sparks,fx_glows,fx_flash
    fx_stop(); fx_t0=fx_last=pygame.time.get_ticks()
    fx_events=sorted((int(e[0]*1000),e[1],int(e[2]*1000) if len(e)>2 else 0) for e in FX_TIMELINES.get(kind,[]))

def _burst(x,y,col,n,speed,life):
    for _ in range(n):
        a=random.random()*math.tau; sp=speed*(0.25+0.75*random.random())
        fx_sparks.append([x,y,math.cos(a)*sp,math.sin(a)*sp,life*(0.7+0.6*random.random()),0.0,col,x,y])

def fx_draw():
    """Lights up the scene in sync with the bangs: flashes, glowing sparks, rockets with light trails."""
    global fx_flash,fx_last,FX_LAYER
    if not (fx_events or fx_rockets or fx_sparks or fx_glows or fx_flash>0.01): return
    if FX_LAYER is None: FX_LAYER=pygame.Surface((VW,VH))
    now=pygame.time.get_ticks(); t=now-fx_t0; dt=min(0.05,max(0.0,(now-fx_last)/1000)); fx_last=now
    while fx_events and fx_events[0][0]<=t:
        ev=fx_events.pop(0); kind=ev[1]
        if kind=='pop':
            x=random.randint(int(VW*.06),int(VW*.94)); y=random.randint(int(VH*.65),int(VH*.9)); col=random.choice(FX_PALETTE)
            _burst(x,y,col,10,150,0.5); fx_glows.append([x,y,45,col,0.25,0.0])
        elif kind=='boom':
            x=random.randint(int(VW*.12),int(VW*.88)); y=random.randint(int(VH*.14),int(VH*.5)); col=random.choice(FX_PALETTE)
            _burst(x,y,col,90,300,1.0); _burst(x,y,(255,255,255),30,170,0.7); fx_glows.append([x,y,230,col,0.8,0.0]); fx_flash=1.0
        elif kind=='launch':
            fx_rockets.append({'x':random.randint(int(VW*.12),int(VW*.88)),'y0':VH+10.0,'y1':random.randint(int(VH*.14),int(VH*.42)),'t0':ev[0],'t1':max(ev[2],ev[0]+300),'col':random.choice(FX_PALETTE),'trail':[]})
    FX_LAYER.fill((0,0,0))
    alive=[]
    for r in fx_rockets:
        p=(t-r['t0'])/(r['t1']-r['t0'])
        if p>=1:
            _burst(r['x'],r['y1'],r['col'],100,320,1.1); _burst(r['x'],r['y1'],(255,255,255),25,150,0.7)
            fx_glows.append([r['x'],r['y1'],230,r['col'],0.9,0.0]); fx_flash=max(fx_flash,0.9); continue
        y=r['y0']+(r['y1']-r['y0'])*(1-(1-max(0,p))**2); x=r['x']+6*math.sin(p*18)
        r['trail'].append((x,y)); r['trail']=r['trail'][-14:]
        for i,(tx,ty) in enumerate(r['trail']):
            k=(i+1)/len(r['trail']); pygame.draw.circle(FX_LAYER,(int(255*k),int(180*k),int(80*k)),(int(tx),int(ty)),2)
        FX_LAYER.blit(glow_sprite(22,(255,200,120)),(int(x)-22,int(y)-22),special_flags=pygame.BLEND_ADD); alive.append(r)
    fx_rockets[:]=alive
    gl=[]
    for g in fx_glows:
        g[5]+=dt
        if g[5]>=g[4]: continue
        FX_LAYER.blit(glow_sprite(g[2],_tier(g[3],1-g[5]/g[4])),(int(g[0])-g[2],int(g[1])-g[2]),special_flags=pygame.BLEND_ADD); gl.append(g)
    fx_glows[:]=gl
    sp_alive=[]; drag=0.35**dt
    for s in fx_sparks:
        s[5]+=dt
        if s[5]>=s[4]: continue
        s[7],s[8]=s[0],s[1]; s[2]*=drag; s[3]=s[3]*drag+260*dt; s[0]+=s[2]*dt; s[1]+=s[3]*dt
        c=_tier(s[6],1-s[5]/s[4])
        pygame.draw.line(FX_LAYER,c,(int(s[7]),int(s[8])),(int(s[0]),int(s[1])),2)
        FX_LAYER.blit(glow_sprite(9,c),(int(s[0])-9,int(s[1])-9),special_flags=pygame.BLEND_ADD); sp_alive.append(s)
    fx_sparks[:]=sp_alive
    fx_flash=max(0.0,fx_flash-dt*3.0); v=int(60*fx_flash**2)
    if v>0: screen.fill((v,v,int(v*0.9)),special_flags=pygame.BLEND_ADD)      # light from the explosion falls on everything
    screen.blit(FX_LAYER,(0,0),special_flags=pygame.BLEND_ADD)

def draw_trophy(cx,cy,t):
    """Golden trophy lit by a glowing light and slowly turning beams."""
    global TR_LAYER
    if TR_LAYER is None: TR_LAYER=pygame.Surface((376,236))
    TR_LAYER.fill((0,0,0)); ox,oy=cx-312,cy-190
    for k in range(14):
        a=t*0.0007+k*2*math.pi/14
        pygame.draw.polygon(TR_LAYER,(64,50,14),[(ox,oy),(ox+190*math.cos(a-0.07),oy+190*math.sin(a-0.07)),(ox+190*math.cos(a+0.07),oy+190*math.sin(a+0.07))])
    TR_LAYER.blit(glow_sprite(120,(255,190,60)),(ox-120,oy-120),special_flags=pygame.BLEND_ADD)
    screen.blit(TR_LAYER,(312,190),special_flags=pygame.BLEND_ADD)
    cy=cy+int(4*math.sin(t*0.006)); gold=(255,196,40); dgold=(222,148,16); lgold=(255,228,120)
    for sg in (-1,1):
        pygame.draw.ellipse(screen,dgold,pygame.Rect(cx+sg*50-16,cy-42,32,40),6)
    pygame.draw.polygon(screen,gold,[(cx-42,cy-50),(cx+42,cy-50),(cx+35,cy-6),(cx+17,cy+14),(cx-17,cy+14),(cx-35,cy-6)])
    pygame.draw.polygon(screen,lgold,[(cx-34,cy-46),(cx-22,cy-46),(cx-26,cy-6),(cx-14,cy+9),(cx-17,cy+9),(cx-29,cy-6)])
    pygame.draw.rect(screen,dgold,(cx-42,cy-54,84,8),border_radius=4)
    pygame.draw.rect(screen,dgold,(cx-7,cy+14,14,20)); pygame.draw.rect(screen,gold,(cx-26,cy+32,52,12),border_radius=4)
    pygame.draw.rect(screen,(120,78,34),(cx-36,cy+44,72,12),border_radius=4)
    pygame.draw.polygon(screen,(255,255,255),_star_pts(cx,cy-24,14))
    for k in range(7):
        ph=(t*0.004+k*0.9)%2.0
        if ph<1.0:
            r=int(10*math.sin(ph*math.pi)); x=cx+int(115*math.cos(k*0.9+1.1)); y=cy-8+int(70*math.sin(k*1.7))
            pygame.draw.polygon(screen,(255,214,60),_star_pts(x,y,r+2,0,4,0.3))

def _dim(alpha):
    ov=pygame.Surface((VW,VH),pygame.SRCALPHA); ov.fill((0,0,0,alpha)); screen.blit(ov,(0,0))

def draw_level_box():
    t=pygame.time.get_ticks()-box_open_t; acc=THEMES[theme_index]['accent']
    rounded(pygame.Rect(300,180,400,380),(14,20,44),28,acc,4)
    screen.set_clip(pygame.Rect(312,190,376,236)); draw_trophy(500,318,t); screen.set_clip(None)
    txt(f'LEVEL {level} COMPLETE!',500,438,bigfont,(255,255,255),True)
    txt(f'+50 BONUS    SCORE {score}',500,462,small,(170,185,220),True)
    button(BTN_NEXT,f'START LEVEL {level+1}',(16,155,75),True,font)
    txt(f'Next level starts in {max(0,AUTO_MS-t)//1000+1}s',500,543,tiny,(170,185,220),True)
    pygame.draw.rect(screen,(40,52,90),(370,553,260,4),border_radius=2)
    pw=int(260*min(1,t/AUTO_MS))
    if pw>1: pygame.draw.rect(screen,acc,(370,553,pw,4),border_radius=2)

def draw_daily_box():
    t=pygame.time.get_ticks()-daily_open_t; acc=THEMES[theme_index]['accent']; d=daily_date or datetime.date.today()
    rounded(pygame.Rect(300,180,400,380),(14,20,44),28,acc,4)
    screen.set_clip(pygame.Rect(312,190,376,236)); draw_trophy(500,318,t); screen.set_clip(None)
    txt('DAILY CHALLENGE',500,430,font,(255,205,65),True)
    txt('COMPLETE!',500,462,bigfont,(255,255,255),True)
    txt(f'{calendar.month_name[d.month]} {d.day}    SCORE {score}',500,498,small,(170,185,220),True)
    button(pygame.Rect(370,515,260,40),'BACK TO DAILY',(16,155,75),True,small)

def draw_retry_box():
    red=(225,60,80)
    rounded(pygame.Rect(300,215,400,335),(14,20,44),28,red,4)
    pygame.draw.circle(screen,red,(468,300),30); pygame.draw.circle(screen,red,(532,300),30)
    pygame.draw.polygon(screen,red,[(440,318),(560,318),(500,385)])
    pygame.draw.lines(screen,(14,20,44),False,[(500,275),(488,300),(508,318),(494,345),(500,368)],4)
    txt(retry_box,500,425,bigfont,(255,255,255),True)
    txt(f'Level {level}   Score {score}',500,455,small,(170,185,220),True)
    button(BTN_NEXT,f'RETRY LEVEL {level}',(16,155,75),True,font)

def show_loading(text):
    _dim(170); txt(text,VW//2,VH//2,bigfont,(255,255,255),True); present()

def go_next_level():
    global level,board,moving,flash,history,awaiting_next,game_start_ms,hint_index,lives,eraser_mode,max_level
    show_loading(f'LOADING LEVEL {level+1}...')
    level+=1; max_level=max(max_level,level); save_data(); board=new_board(); now=pygame.time.get_ticks()
    moving={}; flash={}; history=[]; hint_index=None; eraser_mode=False; awaiting_next=False; fx_stop()
    lives=min(lives_for(level),max(lives,1)); begin_level()
    show_intro(); say(f'LEVEL {level}! {len(board)} arrows - tougher, and fewer helps!')

# ======================= BUILT-IN RELAY SERVER (host does not need a separate file) =======================
import string
_srv_rooms = {}; _srv_lock = threading.Lock(); _srv_started = {}

def _srv_send(conn, obj):
    try: conn.sendall((json.dumps(obj)+'\n').encode())
    except Exception: pass

def _srv_code():
    while True:
        c = ''.join(random.choice(string.ascii_uppercase+string.digits) for _ in range(4))
        if c not in _srv_rooms: return c

def local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.connect(('8.8.8.8', 80)); ip = s.getsockname()[0]; s.close(); return ip
    except Exception: return '127.0.0.1'

def _srv_handle(conn):
    code = None; role = None; buf = b''
    try:
        while True:
            data = conn.recv(65536)
            if not data: break
            buf += data
            while b'\n' in buf:
                line, buf = buf.split(b'\n', 1)
                if not line.strip(): continue
                m = json.loads(line.decode()); op = m.get('op')
                if op == 'create':
                    with _srv_lock:
                        code = _srv_code(); role = 'host'; _srv_rooms[code] = {'host': conn, 'guest': None}
                    _srv_send(conn, {'op': 'created', 'code': code})
                elif op == 'join':
                    c = str(m.get('code', '')).upper()
                    with _srv_lock:
                        room = _srv_rooms.get(c)
                        if room is None: _srv_send(conn, {'op': 'error', 'msg': 'Room not found. Check the code.'}); continue
                        if room['guest'] is not None: _srv_send(conn, {'op': 'error', 'msg': 'Room is already full.'}); continue
                        room['guest'] = conn; code = c; role = 'guest'; host = room['host']
                    _srv_send(conn, {'op': 'joined'}); _srv_send(host, {'op': 'peer_joined'})
                elif op == 'msg' and code:
                    with _srv_lock:
                        room = _srv_rooms.get(code)
                        peer = None if room is None else (room['guest'] if role == 'host' else room['host'])
                    if peer: _srv_send(peer, {'op': 'msg', 'data': m.get('data')})
    except Exception: pass
    finally:
        if code:
            with _srv_lock:
                room = _srv_rooms.get(code)
                if room:
                    if role == 'host':
                        g = room['guest']; _srv_rooms.pop(code, None)
                        if g: _srv_send(g, {'op': 'peer_left'})
                    else:
                        room['guest'] = None; _srv_send(room['host'], {'op': 'peer_left'})
        try: conn.close()
        except Exception: pass

def start_embedded_server(port):
    """Start OUR relay inside the game on `port`. Returns False when the port is taken by another program/old game.
    (On Windows SO_REUSEADDR would silently let two programs share one port, so an old relay could answer instead of ours.)"""
    if _srv_started.get(port): return True
    try:
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        if sys.platform == 'win32': srv.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        else: srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(('0.0.0.0', port)); srv.listen(10)
    except OSError:
        return False
    def loop():
        while True:
            try: conn, _ = srv.accept()
            except Exception: break
            threading.Thread(target=_srv_handle, args=(conn,), daemon=True).start()
    threading.Thread(target=loop, daemon=True).start(); _srv_started[port] = True; return True

# ======================= ONLINE: play with friends =======================
class NetClient:
    """Talks to arrow_relay_server.py (one JSON message per line). Reading happens in a background thread."""
    def __init__(self):
        self.sock=None; self.q=queue.Queue(); self.alive=False
    def connect(self,host,port):
        try:
            self.sock=socket.create_connection((host,port),timeout=6); self.sock.settimeout(None); self.alive=True
            self.q.put({'op':'conn_ok'}); self._read()
        except Exception as ex:
            self.q.put({'op':'conn_fail','msg':str(ex)[:70]})
    def _read(self):
        buf=b''
        try:
            while True:
                data=self.sock.recv(65536)
                if not data: break
                buf+=data
                while b'\n' in buf:
                    line,buf=buf.split(b'\n',1)
                    if line.strip(): self.q.put(json.loads(line.decode()))
        except Exception: pass
        self.alive=False; self.q.put({'op':'closed'})
    def send(self,obj):
        try: self.sock.sendall((json.dumps(obj)+'\n').encode())
        except Exception: self.alive=False
    def close(self):
        self.alive=False
        try: self.sock.shutdown(socket.SHUT_RDWR)
        except Exception: pass
        try: self.sock.close()
        except Exception: pass


# ======================= INTERNET ROOMS: free public MQTT relay (works through firewalls / college Wi-Fi) =======================
import time
MQTT_BROKERS=[('broker.emqx.io',1883),('broker.hivemq.com',1883),('test.mosquitto.org',1883)]
_MQ_ALPHA='ABCDEFGHJKLMNPQRSTUVWXYZ23456789'

def _mq_str(s):
    b=s.encode(); return len(b).to_bytes(2,'big')+b

def _mq_pkt(first,body):
    n=len(body); out=bytearray([first])
    while True:
        b=n%128; n//=128; out.append(b|128 if n else b)
        if not n: break
    return bytes(out)+body

def _mq_parse(buf):
    """-> (first_byte, body, rest) or None while the packet is still incomplete."""
    if len(buf)<2: return None
    n=0; mult=1; i=1
    while True:
        if i>=len(buf): return None
        b=buf[i]; i+=1; n+=(b&127)*mult; mult*=128
        if not b&128: break
        if i>4: raise ValueError('bad length')
    if len(buf)<i+n: return None
    return buf[0],buf[i:i+n],buf[i+n:]

class MqttClient:
    """Same interface as NetClient, but both players connect OUT to a free public MQTT broker.
    No ports to open, no firewall question, works on college Wi-Fi / mobile data / different networks."""
    def __init__(self):
        self.sock=None; self.q=queue.Queue(); self.alive=False; self.lock=threading.Lock()
        self.role=None; self.code=None; self.gid=None; self.joined=False; self.peer_ok=False
        self.last_rx=0; self.last_tx=0; self.hb_at=0; self.hello_at=0
    def _tx(self,data):
        with self.lock:
            try: self.sock.sendall(data); self.last_tx=time.time()
            except Exception: self.alive=False
    def _topic(self,to): return f'arrowpuzzle14/{self.code}/{to}'          # 'h' = to host, 'g' = to guest
    def _sub(self,to): self._tx(_mq_pkt(0x82,b'\x00\x01'+_mq_str(self._topic(to))+b'\x00'))
    def _pub(self,m,gid=None):
        m=dict(m); m['id']=gid or self.gid
        self._tx(_mq_pkt(0x30,_mq_str(self._topic('g' if self.role=='host' else 'h'))+json.dumps(m,separators=(',',':')).encode()))
    def connect(self,host,port):
        err='offline?'
        for bh,bp in MQTT_BROKERS:
            try:
                s=socket.create_connection((bh,bp),timeout=6)
                cid='ap'+''.join(random.choice(_MQ_ALPHA) for _ in range(10))
                s.sendall(_mq_pkt(0x10,_mq_str('MQTT')+bytes([4,2])+(30).to_bytes(2,'big')+_mq_str(cid)))
                s.settimeout(6); resp=s.recv(4)
                if len(resp)>=4 and resp[0]==0x20 and resp[3]==0:
                    self.sock=s; s.settimeout(1.0); self.alive=True; self.last_rx=self.last_tx=time.time()
                    dbg('MQTT connected',bh,bp); self.q.put({'op':'conn_ok'}); self._read(); return
                s.close(); err=f'{bh} refused'
            except Exception as ex: err=f'{bh}: {str(ex)[:30]}'
            dbg('MQTT broker failed',err)
        self.q.put({'op':'conn_fail','msg':'Internet relay unreachable - check internet. '+err[:40]})
    def _read(self):
        buf=b''
        try:
            while self.alive:
                try: data=self.sock.recv(65536)
                except socket.timeout: data=None
                if data==b'': break
                if data: buf+=data
                while True:
                    p=_mq_parse(buf)
                    if p is None: break
                    first,body,buf=p
                    if first>>4==3: self._on_publish(first,body)
                self._tick()
        except Exception as ex: dbg('MQTT read error',ex)
        self.alive=False; self.q.put({'op':'closed'})
    def _on_publish(self,first,body):
        tl=int.from_bytes(body[:2],'big'); off=2+tl+(2 if (first>>1)&3 else 0)
        try: m=json.loads(body[off:].decode())
        except Exception: return
        self._handle(m)
    def _handle(self,m):
        t=m.get('t'); now=time.time()
        if self.role=='host':
            if t=='hello':
                if self.peer_ok and m.get('id')==self.gid: self._pub({'t':'welcome'})
                elif not self.peer_ok:
                    self.gid=m.get('id'); self.peer_ok=True; self.last_rx=self.hb_at=now
                    self._pub({'t':'welcome'}); self.q.put({'op':'peer_joined'})
                else: self._pub({'t':'full'},m.get('id'))
                return
        if m.get('id')!=self.gid: return
        self.last_rx=now
        if t=='welcome' and self.role=='guest' and not self.joined:
            self.joined=True; self.peer_ok=True; self.hello_at=0; self.hb_at=now; self.q.put({'op':'joined'})
        elif t=='full' and self.role=='guest': self.hello_at=0; self.q.put({'op':'error','msg':'Room is already full.'})
        elif t=='msg': self.q.put({'op':'msg','data':m.get('data')})
        elif t=='bye':
            self.peer_ok=False
            if self.role=='host': self.gid=None
            self.q.put({'op':'peer_left'})
    def _tick(self):
        now=time.time()
        if now-self.last_tx>15: self._tx(b'\xc0\x00')                       # MQTT keep-alive
        if self.peer_ok and now-self.hb_at>4: self.hb_at=now; self._pub({'t':'hb'})
        if self.peer_ok and now-self.last_rx>25:                           # friend vanished without saying bye
            self.peer_ok=False
            if self.role=='host': self.gid=None
            self.q.put({'op':'peer_left'})
        if self.role=='guest' and not self.joined and self.hello_at and now-self.hello_at>8:
            self.hello_at=0; self.q.put({'op':'error','msg':'Room not found. Check the code, or the host is offline.'})
    def send(self,obj):
        op=obj.get('op')
        if op=='create':
            self.role='host'; self.code=''.join(random.choice(_MQ_ALPHA) for _ in range(6)); self._sub('h')
            self.q.put({'op':'created','code':self.code})
        elif op=='join':
            self.role='guest'; self.code=str(obj.get('code','')).upper(); self.gid=''.join(random.choice(_MQ_ALPHA) for _ in range(8))
            self._sub('g'); self.hello_at=time.time(); self._pub({'t':'hello'})
        elif op=='msg': self._pub({'t':'msg','data':obj.get('data')})
    def close(self):
        try:
            if self.alive and self.peer_ok: self._pub({'t':'bye'})
            if self.alive: self._tx(b'\xe0\x00')
        except Exception: pass
        self.alive=False
        try: self.sock.shutdown(socket.SHUT_RDWR)
        except Exception: pass
        try: self.sock.close()
        except Exception: pass

net_mode='lan'

net=None; online_modal=False; online_state=None; online_role=None; my_turn=0
race_start=0; race_result=None; race_my_ms=0; race_box_t=0; opp_left=0; opp_lives=3; opp_out=False; me_out=False
join_target=''; lan_addr=''; net_server_text='127.0.0.1:5050'; net_invite_text=''; online_code=''; net_msg=''; active_field='server'; pending_op=None

def online_on(): return online_state=='connected' and net is not None and net.alive
def guard(fn):
    if online_on(): say('Hints and power-ups are off in online battle.'); play_sfx('click')
    else: fn()

def open_online():
    global online_modal
    online_modal=True

def net_close():
    global net,online_state,online_role,race_result
    if net is not None: net.close()
    net=None; online_state=None; online_role=None; race_result=None

def parse_server(txt):
    txt=(txt or '').strip() or '127.0.0.1:5050'
    if ':' in txt:
        host,port=txt.rsplit(':',1)
        try: return host.strip(),int(port)
        except ValueError: return host.strip(),5050
    return txt,5050

def net_connect(server_text,op):
    global net,online_state,pending_op,net_msg
    net_close(); host,port=parse_server(server_text)
    dbg('CONNECT',host,port,op.get('op')); net=MqttClient() if net_mode=='net' else NetClient(); pending_op=op; online_state='connecting'; net_msg='Connecting to the internet relay ...' if net_mode=='net' else f'Connecting to {host}:{port} ...'
    threading.Thread(target=net.connect,args=(host,port),daemon=True).start()

def dbg(*a):
    """Writes arrow_online_log.txt next to the game so connection problems can be seen."""
    try:
        with open(Path(__file__).with_name('arrow_online_log.txt'),'a',encoding='utf-8') as f:
            f.write(datetime.datetime.now().strftime('%H:%M:%S ')+' '.join(map(str,a))+'\n')
    except Exception: pass

RELAY_PORT=5050
FW_RULE='ArrowPuzzleRelay'
def ensure_firewall():
    """Windows only: let friends on the same Wi-Fi reach the relay ports. Asks for admin permission ONCE (click Yes)."""
    if sys.platform!='win32': return
    def work():
        try:
            r=subprocess.run(['netsh','advfirewall','firewall','show','rule',f'name={FW_RULE}'],capture_output=True,timeout=15,creationflags=0x08000000)
            if r.returncode==0 and b'No rules' not in r.stdout: dbg('FIREWALL rule already exists'); return
            args=f'advfirewall firewall add rule name={FW_RULE} dir=in action=allow protocol=TCP localport=5050-5069 profile=any'
            ps=f"Start-Process netsh -ArgumentList '{args}' -Verb RunAs -WindowStyle Hidden -Wait"
            subprocess.run(['powershell','-NoProfile','-Command',ps],timeout=90,capture_output=True,creationflags=0x08000000)
            dbg('FIREWALL rule added')
        except Exception as ex: dbg('FIREWALL error',ex)
    threading.Thread(target=work,daemon=True).start()

def create_room():
    """Host: our relay starts inside the game on the first free port (5050, 5051, ...).
    Host connects to it locally. The invite = public address typed in the Server box (ngrok/playit),
    otherwise this computer's Wi-Fi/LAN address, always with the REAL port."""
    global lan_addr,net_msg,net_mode
    net_mode='lan'; save_data(); host,port=parse_server(net_server_text)
    used=next((q for q in range(RELAY_PORT,RELAY_PORT+20) if start_embedded_server(q)),None)
    if used is None: net_msg='Could not start the relay server (ports 5050-5069 busy). Close old game windows.'; return
    ensure_firewall()
    local_hosts=('127.0.0.1','localhost','0.0.0.0',local_ip())
    lan_addr=f'{local_ip()}:{used}' if host in local_hosts else f'{host}:{port}'
    dbg('CREATE relay_port',used,'invite_addr',lan_addr,'game',VERSION); net_connect(f'127.0.0.1:{used}',{'op':'create'})

def create_room_net():
    """Host an INTERNET room: both players connect OUT to a free public relay, so firewall / Wi-Fi isolation never blocks it."""
    global net_mode,lan_addr
    net_mode='net'; lan_addr=''; dbg('CREATE internet room',VERSION); net_connect('internet:0',{'op':'create'})

def join_room():
    global net_msg,join_target,net_mode
    t=net_invite_text.strip()
    if not t: net_msg='Paste the invite code your friend sent you.'; return
    if '/' in t: server,code=t.rsplit('/',1)
    elif len(t)==6 and t.isalnum(): server,code='net',t
    else: net_msg='Paste the FULL invite (like net/ABC123 or 10.30.4.83:5051/ABCD).'; return
    if server.strip().lower() in ('net','internet'):
        net_mode='net'; join_target=''; net_connect('internet:0',{'op':'join','code':code.strip().upper()}); return
    net_mode='lan'; join_target=server.strip(); net_connect(server,{'op':'join','code':code.strip().upper()})

def invite_string(): return f"net/{online_code}" if net_mode=='net' else f"{lan_addr or net_server_text.strip()}/{online_code}"

def invite_message():
    return f"Join my Arrow Puzzle battle! Open the game > ONLINE > paste this invite code: {invite_string()}"

def clip_set(text):
    try:
        import tkinter
        r=tkinter.Tk(); r.withdraw(); r.clipboard_clear(); r.clipboard_append(text); r.update(); r.destroy(); return True
    except Exception: return False

def clip_get():
    try:
        import tkinter
        r=tkinter.Tk(); r.withdraw(); t=r.clipboard_get(); r.destroy(); return t
    except Exception: return ''

def host_start_online():
    """Host: make a new board, start playing as P1 and send the same board to the friend."""
    global game_mode,my_turn,online_modal,race_start,opp_left
    if not online_on(): return
    game_mode='Friends Battle'; my_turn=0; start_game(); online_modal=False
    race_start=pygame.time.get_ticks()+3000; opp_left=len(board)         # 3-2-1 countdown, then BOTH race on the same board
    net.send({'op':'msg','data':{'k':'start','arrows':[{'cells':[list(c) for c in a['cells']],'dir':a['dir']} for a in board]}})
    say('Same puzzle for both of you - first to clear it wins!')

def guest_start_online(d):
    global game_mode,my_turn,online_modal,race_start,opp_left
    global page
    page='game'; set_grid(1); arrows=[]
    for a in d.get('arrows',[]):
        cells=[tuple(c) for c in a['cells']]
        arrows.append({'cells':cells,'points':compress(cells),'dir':a['dir'],'removed':False})
    game_mode='Friends Battle'; my_turn=1; start_game(arrows); online_modal=False
    race_start=pygame.time.get_ticks()+3000; opp_left=len(arrows)
    say('Same puzzle for both of you - first to clear it wins!')

def race_countdown(): return bool(race_start) and pygame.time.get_ticks()<race_start

def board_tap(idx):
    if race():
        if race_countdown() or race_result is not None: return
        tap_arrow(idx); send_prog(); return
    tap_arrow(idx)

def send_prog():
    if online_on(): net.send({'op':'msg','data':{'k':'prog','left':sum(1 for c in board if not c['removed']),'lives':lives}})

def set_race_result(res,reason=''):
    """Race over: res is 'win', 'lose' or 'draw'."""
    global race_result,playing,page,race_box_t,battle_wins
    playing=False; page='game'; race_box_t=pygame.time.get_ticks(); pending.clear(); fx_stop()
    race_result={'res':res,'reason':reason}
    if res=='win': battle_wins+=1; save_data(); game_finale()
    elif res=='lose': play_sfx('lose')
    say({'win':'YOU WIN! ','lose':'YOU LOSE. ','draw':'DRAW. '}[res]+reason)

def race_finished_local():
    global race_my_ms
    race_my_ms=max(0,pygame.time.get_ticks()-race_start)
    net.send({'op':'msg','data':{'k':'done','t':race_my_ms}})
    set_race_result('win','You cleared the puzzle first!')

def race_out():
    global me_out
    me_out=True; net.send({'op':'msg','data':{'k':'out'}})
    if opp_out: set_race_result('draw','Both of you ran out of lives.')
    else: set_race_result('lose','You ran out of lives.')

def handle_net_msg(d):
    global opp_left,opp_lives,opp_out,battle_wins
    k=d.get('k')
    if k=='start': guest_start_online(d)
    elif k=='prog': opp_left=int(d.get('left',opp_left)); opp_lives=int(d.get('lives',opp_lives))
    elif k=='done':
        t=int(d.get('t',0))
        if race_result is None and playing:
            set_race_result('lose','Your friend cleared it first!'); race_result['opp_ms']=t
        elif race_result and race_result['res']=='win' and (t<race_my_ms or (t==race_my_ms and online_role=='guest')):
            battle_wins=max(0,battle_wins-1); set_race_result('lose','Your friend was a split second faster!'); race_result['opp_ms']=t
    elif k=='out':
        opp_out=True
        if race_result is None and playing: set_race_result('win','Your friend ran out of lives!')
        elif race_result and race_result['res']=='lose' and me_out: set_race_result('draw','Both of you ran out of lives.')

def draw_race_hud():
    t=THEMES[theme_index]; panel=t['panel']; acc=t['accent']
    rounded(pygame.Rect(15,480,235,150),panel,20,acc,2); txt('ONLINE RACE',35,492,small,acc)
    total=max(1,len(board)); mine=sum(1 for c in board if not c['removed']); theirs=max(0,min(opp_left,total))
    for y,label,left,col,lv in ((518,'YOU',mine,acc,lives),(572,'FRIEND',theirs,(255,150,60),opp_lives)):
        txt(label,35,y,tiny,(255,255,255)); s=f'{left} left'; txt(s,230-tiny.size(s)[0],y,tiny,(255,255,255))
        pygame.draw.rect(screen,(40,52,90),(35,y+18,195,10),border_radius=5)
        w=int(195*(1-left/total))
        if w>1: pygame.draw.rect(screen,col,(35,y+18,w,10),border_radius=5)
        txt('♥ '*max(0,lv) if lv>0 else 'OUT',35,y+30,tiny,(245,65,90))

def draw_race_overlay():
    now=pygame.time.get_ticks()
    if not race_start or race_result is not None: return
    if now<race_start:
        _dim(150); n=(race_start-now)//1000+1
        txt('GET READY!',VW//2,330,bigfont,(255,255,255),True); txt(n,VW//2,420,hugefont,(255,214,60),True)
        txt('Same puzzle for both - first to clear it wins!',VW//2,500,small,(190,205,235),True)
    elif now-race_start<700 and playing: txt('GO!',VW//2,400,hugefont,(90,255,150),True)

RB_REMATCH=pygame.Rect(370,520,260,50); RB_LEAVE=pygame.Rect(370,582,260,44)
def draw_race_box():
    r=race_result; res=r['res']; t=pygame.time.get_ticks()-race_box_t
    col={'win':(60,200,110),'lose':(225,60,80),'draw':(240,170,50)}[res]; bg=(14,20,44)
    rounded(pygame.Rect(300,170,400,480),bg,28,col,4)
    if res=='win':
        screen.set_clip(pygame.Rect(312,190,376,236)); draw_trophy(500,318,t); screen.set_clip(None)
    elif res=='lose':
        pygame.draw.circle(screen,col,(468,290),30); pygame.draw.circle(screen,col,(532,290),30)
        pygame.draw.polygon(screen,col,[(440,308),(560,308),(500,375)])
        pygame.draw.lines(screen,bg,False,[(500,265),(488,290),(508,308),(494,335),(500,358)],4)
    else:
        pygame.draw.circle(screen,col,(500,300),58); txt('=',500,300,hugefont,bg,True)
    txt({'win':'YOU WIN!','lose':'YOU LOSE','draw':'DRAW'}[res],500,440,bigfont,(255,255,255),True)
    txt(r.get('reason','')[:46],500,468,small,(190,205,235),True)
    if res=='win': info=f'Your time: {race_my_ms/1000:.1f}s'
    elif res=='lose' and r.get('opp_ms') is not None: info=f"Friend's time: {r['opp_ms']/1000:.1f}s"
    else: info=f"Arrows left - you: {sum(1 for c in board if not c['removed'])}   friend: {opp_left}"
    txt(info,500,494,small,(255,214,60),True)
    if online_on() and online_role=='host': button(RB_REMATCH,'REMATCH',(16,155,75),True,font)
    elif online_on(): txt('Waiting for the host to start a rematch...',500,545,tiny,(170,185,220),True)
    button(RB_LEAVE,'LEAVE ROOM',(170,40,50),True,font)

def net_poll():
    global online_state,online_role,online_code,net_msg,playing
    while net is not None:
        try: m=net.q.get_nowait()
        except queue.Empty: break
        op=m.get('op'); dbg('EVENT',op,m.get('msg',''),m.get('code',''))
        if op=='conn_ok': net.send(pending_op)
        elif op=='conn_fail':
            why=m.get('msg',''); net_msg='Timed out - firewall/Wi-Fi blocked. Try phone hotspot.' if 'timed out' in why.lower() else 'Cannot connect: '+why; net_close()
        elif op=='created': online_code=m['code']; online_role='host'; online_state='waiting'; net_msg=''
        elif op=='joined': online_role='guest'; online_state='connected'; net_msg='Joined! Waiting for the host to start...'; say('Joined! Waiting for the host to start...')
        elif op=='peer_joined': online_state='connected'; host_start_online()
        elif op=='error': net_msg=m.get('msg','Error')+(f' [{join_target}] Paste the FULL invite (address/CODE).' if (pending_op or {}).get('op')=='join' and join_target else ''); net_close()
        elif op=='peer_left':
            if playing and race_result is None and game_mode=='Friends Battle' and online_role=='host': set_race_result('win','Your friend left the match.')
            playing=False
            if online_role=='host': online_state='waiting'; net_msg='Friend left. Room is open again.'; say('Friend left. Room is open for a new friend.')
            else: net_msg='The host left.'; say('The host left the game.'); net_close()
        elif op=='closed':
            if online_state is not None:
                net_msg='Disconnected from server.'; say('Disconnected from the online room.'); playing=False
            net_close()
        elif op=='msg': handle_net_msg(m.get('data') or {})

OM=pygame.Rect(240,140,520,520)
def om_buttons():
    r={'close':pygame.Rect(380,596,240,46)}
    if online_state in (None,'menu'):
        r.update({'server':pygame.Rect(270,218,460,40),'create':pygame.Rect(270,268,225,46),'create_net':pygame.Rect(505,268,225,46),'invite':pygame.Rect(270,386,460,40),'join':pygame.Rect(270,436,460,46)})
    elif online_state=='waiting':
        r.update({'wa':pygame.Rect(270,420,215,48),'copy':pygame.Rect(515,420,215,48),'leave':pygame.Rect(270,484,460,46)})
    else:
        r.update({'leave':pygame.Rect(270,484,460,46)})
    return r

def online_click(pos):
    global online_modal,active_field,net_msg
    r=om_buttons()
    if not OM.collidepoint(pos): return
    if r['close'].collidepoint(pos): online_modal=False; return
    if 'server' in r and r['server'].collidepoint(pos): active_field='server'
    elif 'invite' in r and r['invite'].collidepoint(pos): active_field='invite'
    elif 'create' in r and r['create'].collidepoint(pos): play_sfx('click'); create_room()
    elif 'create_net' in r and r['create_net'].collidepoint(pos): play_sfx('click'); create_room_net()
    elif 'join' in r and r['join'].collidepoint(pos): play_sfx('click'); join_room()
    elif 'wa' in r and r['wa'].collidepoint(pos): webbrowser.open('https://wa.me/?text='+urllib.parse.quote(invite_message()))
    elif 'copy' in r and r['copy'].collidepoint(pos): net_msg='Invite copied!' if clip_set(invite_string()) else 'Could not copy - select the code and copy it by hand.'
    elif 'leave' in r and r['leave'].collidepoint(pos): net_close(); net_msg=''; say('Left the online room.')

def online_key(e):
    global online_modal,net_server_text,net_invite_text,active_field
    if e.key==pygame.K_ESCAPE: online_modal=False; return
    if online_state not in (None,'menu'): return
    if e.key==pygame.K_TAB: active_field='invite' if active_field=='server' else 'server'; return
    if e.key==pygame.K_RETURN:
        if active_field=='server': create_room()
        else: join_room()
        return
    cur=net_server_text if active_field=='server' else net_invite_text
    if (e.mod & pygame.KMOD_CTRL) and e.key==pygame.K_v: cur=clip_get().strip().replace('\n','')[:90]
    elif e.key==pygame.K_BACKSPACE: cur=cur[:-1]
    elif e.unicode and e.unicode.isprintable() and len(cur)<90: cur+=e.unicode
    if active_field=='server': net_server_text=cur
    else: net_invite_text=cur

def _field(rect,text,active):
    rounded(rect,(10,16,36),8,(0,190,225) if active else (70,85,120),2)
    shown=text[-44:]+('|' if active and (pygame.time.get_ticks()//500)%2 else '')
    txt(shown,rect.x+10,rect.centery-8,small,(255,255,255))

def draw_online_box():
    acc=THEMES[theme_index]['accent']; r=om_buttons()
    rounded(OM,(14,20,44),26,(150,100,230),4)
    txt('PLAY WITH FRIENDS ONLINE',500,168,font,(255,255,255),True); txt(VERSION,735,152,tiny,(130,145,185),True)
    if online_state in (None,'menu'):
        txt('1) HOST A GAME - server address (the relay server)',270,196,tiny,(170,185,220))
        _field(r['server'],net_server_text,active_field=='server'); button(r['create'],'CREATE: WI-FI',(0,125,205),True,font); button(r['create_net'],'CREATE: INTERNET',(16,155,75),True,font)
        txt('INTERNET = works on ANY network (college Wi-Fi, mobile data). No setup.',270,324,tiny,(130,145,185))
        txt('WI-FI = same network only, uses the address above.',270,340,tiny,(130,145,185))
        txt('2) JOIN A FRIEND - paste the invite code (Ctrl+V)',270,364,tiny,(170,185,220))
        _field(r['invite'],net_invite_text,active_field=='invite'); button(r['join'],'JOIN ROOM',(110,70,200),True,font)
    elif online_state=='connecting':
        txt('Connecting...',500,300,bigfont,(255,255,255),True); button(r['leave'],'CANCEL',(170,40,50),True,font)
    elif online_state=='waiting':
        txt('ROOM CODE',500,228,small,(170,185,220),True); txt(online_code,500,282,pygame.font.SysFont('arial',60,bold=True),(255,214,60),True)
        txt('Friend pastes this invite code in ONLINE > JOIN ROOM:',500,340,tiny,(170,185,220),True)
        txt(invite_string(),500,366,font,(255,255,255),True)
        if invite_string().startswith(('127.','localhost')): txt('(127.0.0.1 only works on this computer - type your Wi-Fi/tunnel address in Server)',500,392,tiny,(255,150,100),True)
        txt('Internet room: your friend can be on ANY network.' if net_mode=='net' else 'Same Wi-Fi needed. Click YES on the Windows admin prompt. College Wi-Fi blocks? Use an INTERNET room.',500,404,tiny,(130,145,185),True)
        button(r['wa'],'WHATSAPP',(30,160,90),True,font); button(r['copy'],'COPY',(0,125,205),True,font); button(r['leave'],'CLOSE ROOM',(170,40,50),True,font)
    else:
        txt('CONNECTED!',500,300,bigfont,(90,255,150),True)
        txt(f"You are {'P1 (host)' if online_role=='host' else 'P2'}. Both of you get the SAME puzzle.",500,340,small,(255,255,255),True)
        txt('First to clear every arrow wins! 3 wrong taps = knocked out.' ,500,364,small,(170,185,220),True)
        button(r['leave'],'LEAVE ROOM',(170,40,50),True,font)
    if net_msg: txt(net_msg[:95],500,512 if online_state in ('waiting','connected') else 500,small,(255,220,100),True)
    button(r['close'],'CLOSE',(60,75,120),True,font)

def draw_modal(fn):
    """Draw a pop-up designed for a 1000x800 sheet in the middle of the wider canvas."""
    global screen
    real=screen; ms=pygame.Surface((1000,800)); ms.blit(real,(0,0),pygame.Rect(OX,0,1000,800))
    screen=ms
    try: fn()
    finally: screen=real
    real.blit(ms,(OX,0))

# ---------------- level intro pop-up: "Level N - EASY / NORMAL / HARD" ----------------
intro_box=False; intro_open_t=0; INTRO_MS=2800
SHAPE_NAMES={'heart':'Heart','circle':'Circle','diamond':'Diamond','star':'Star','hexagon':'Hexagon','triangle':'Triangle','plus':'Plus','ring':'Ring','moon':'Moon','arrow':'Big Arrow'}

def show_intro():
    """Start immediately: level and difficulty are already on the main screen."""
    dismiss_intro()


def dismiss_intro():
    """The level timer starts fresh the moment the pop-up closes - nothing carries over from the last level."""
    global intro_box,game_start_ms,time_left
    intro_box=False; game_start_ms=pygame.time.get_ticks()
    time_left=time_options[timer_choice] if game_mode=='Time Challenge' else 0

def draw_intro_box():
    t=pygame.time.get_ticks()-intro_open_t; name,col=difficulty_for(level)
    rounded(pygame.Rect(310,265,380,270),(14,20,44),28,col,5)
    txt(f'LEVEL {level}',500,305,bigfont,(255,255,255),True)
    rounded(pygame.Rect(420,338,160,44),col,22,(255,255,255),2); txt(name,500,360,font,(255,255,255),True)
    txt(f'{SHAPE_NAMES.get(SHAPE,SHAPE)} shape   -   {len(board)} arrows',500,408,small,(190,205,235),True)
    txt(f'Timer: {time_options[timer_choice]}s for this level' if game_mode=='Time Challenge' else 'Take your time - no time limit',500,436,small,(190,205,235),True)
    txt('TAP TO START',500,478,small,(255,255,255),True)
    pygame.draw.rect(screen,(40,52,90),(380,500,240,5),border_radius=2)
    pw=int(240*min(1,t/INTRO_MS))
    if pw>1: pygame.draw.rect(screen,col,(380,500,pw,5),border_radius=2)

def hit_arrow(pos):
    best=None;dist=max(8,CELL*0.42)
    for i,c in enumerate(board):
        if c['removed']:continue
        for a,b in path_segments(c):
            d=point_distance_to_segment(pos,a,b)
            if d<dist:best=i;dist=d
    return best

def set_timer(idx):
    global timer_choice,time_left,game_start_ms
    timer_choice=idx; play_sfx('click')
    if game_mode=='Time Challenge':
        time_left=time_options[idx]
        if playing: game_start_ms=pygame.time.get_ticks()
        say(f'TIMER SET TO {time_options[idx]} SECONDS')
    else: say(f'Timer ({time_options[idx]}s) is used in Time Challenge mode')


# ======================= SEPARATE PAGES: Main / Daily / Me (+ the Game page above) =======================
page = 'menu'
daily_done = set()
BLUE = (47, 128, 237)
hugefont = pygame.font.SysFont('arial', 68, bold=True)
midfont = pygame.font.SysFont('arial', 28, bold=True)
daysfont = pygame.font.SysFont('arial', 24, bold=True)
TAB_Y = 730
TABS = [('menu', 'Main'), ('daily', 'Daily'), ('me', 'Me')]
COL_L, COL_W = 390, 500                       # centred column used by the Main and Daily pages
_grad = {}

def vgrad(w, h, c1, c2, radius=0):
    key = (w, h, c1, c2, radius)
    if key not in _grad:
        s = pygame.Surface((w, h), pygame.SRCALPHA)
        for y in range(h):
            f = y/max(1, h-1); pygame.draw.line(s, [int(c1[i]+(c2[i]-c1[i])*f) for i in range(3)]+[255], (0, y), (w, y))
        if radius:
            m = pygame.Surface((w, h), pygame.SRCALPHA); pygame.draw.rect(m, (255, 255, 255, 255), (0, 0, w, h), border_radius=radius)
            s.blit(m, (0, 0), special_flags=pygame.BLEND_RGBA_MIN)
        _grad[key] = s
    return _grad[key]

def tab_rect(i): return pygame.Rect(i*VW//3, TAB_Y, VW//3, VH-TAB_Y)

def draw_tab_icon(kind, cx, cy, col):
    if kind == 'menu':
        pygame.draw.polygon(screen, col, [(cx-22, cy+2), (cx, cy-18), (cx+22, cy+2)]); pygame.draw.rect(screen, col, (cx-15, cy+1, 30, 19), border_radius=3)
        pygame.draw.rect(screen, (255, 255, 255), (cx-4, cy+8, 8, 12))
    elif kind == 'daily':
        pygame.draw.rect(screen, col, (cx-17, cy-14, 34, 32), 3, border_radius=6); pygame.draw.line(screen, col, (cx-10, cy-19), (cx-10, cy-11), 3); pygame.draw.line(screen, col, (cx+10, cy-19), (cx+10, cy-11), 3)
        pygame.draw.polygon(screen, col, _star_pts(cx, cy+3, 8))
    else:
        pygame.draw.circle(screen, col, (cx, cy-7), 10); pygame.draw.ellipse(screen, col, pygame.Rect(cx-17, cy+5, 34, 24))

def draw_tab_bar():
    pygame.draw.rect(screen, (255, 255, 255), (0, TAB_Y, VW, VH-TAB_Y)); pygame.draw.line(screen, (222, 227, 235), (0, TAB_Y), (VW, TAB_Y), 2)
    for i, (k, label) in enumerate(TABS):
        col = BLUE if page == k else (125, 135, 150); r = tab_rect(i)
        draw_tab_icon(k, r.centerx, r.y+26, col); txt(label, r.centerx, r.y+56, small, col, True)

def pill(rect, label, sub=None, color=BLUE, text_col=(255, 255, 255), f=midfont, outline=None):
    pygame.draw.rect(screen, (190, 205, 228), rect.move(0, 5), border_radius=rect.h//2)
    pygame.draw.rect(screen, color, rect, border_radius=rect.h//2)
    if outline: pygame.draw.rect(screen, outline, rect, 3, border_radius=rect.h//2)
    if sub: txt(label, rect.centerx, rect.centery-12, f, text_col, True); txt(sub, rect.centerx, rect.centery+16, small, (205, 225, 252), True)
    else: txt(label, rect.centerx, rect.centery, f, text_col, True)

titlefont = pygame.font.SysFont('arial', 54, bold=True)

def menu_rects():
    r = {'card': pygame.Rect(150, 40, 220, 270), 'new': pygame.Rect(40, 520, 440, 84)}
    r['card_play'] = pygame.Rect(r['card'].x+45, r['card'].bottom-72, 130, 46)
    if game_started and playing: r['resume'] = pygame.Rect(40, 615, 440, 56)
    if saved_start()[0] > 1: r['restart'] = pygame.Rect(90, 682, 340, 36)
    return r

def home_rects():
    """Everything that used to live in Me > Settings (stats, theme, timer, game mode, online) now sits on the home page."""
    AX, BX, W = 520, 900, 360
    return {'stats': pygame.Rect(AX, 40, W, 170), 'theme': pygame.Rect(BX, 40, W, 170),
            'timer': pygame.Rect(AX, 230, W, 110), 'mode': pygame.Rect(BX, 230, W, 260), 'friend': pygame.Rect(AX, 360, W, 130),
            'msg': pygame.Rect(AX, 510, 740, 44),
            'themes': [(BX+46+i*80, 40+88) for i in range(4)],
            'timers': [pygame.Rect(AX+22+i*80, 230+62, 72, 40) for i in range(4)],
            'modes': [pygame.Rect(BX+22, 230+58+i*46, 316, 40) for i in range(4)],
            'online': pygame.Rect(AX+22, 360+54, 316, 56)}

def draw_home_panels():
    t = THEMES[theme_index]; panel = t['panel']; acc = t['accent']; r = home_rects()
    p = r['stats']; rounded(p, panel, 20, acc, 2); txt('STATS', p.x+22, p.y+14, font, acc)
    txt(f'Best: {best_score}', p.x+22, p.y+52, font, (255, 205, 65)); txt(f'Daily streak: {streak} day(s)', p.x+22, p.y+88, small, (100, 220, 255))
    txt('Top: '+', '.join(map(str, top_scores))[:34], p.x+22, p.y+122, small, (255, 255, 255))
    p = r['theme']; rounded(p, panel, 20, acc, 2); txt('THEME', p.x+22, p.y+14, font, acc)
    for i, th in enumerate(THEMES):
        pygame.draw.circle(screen, th['circle'], r['themes'][i], 20)
        if i == theme_index: pygame.draw.circle(screen, (255, 255, 255), r['themes'][i], 26, 3)
    txt(t['name'], p.centerx, p.bottom-22, small, (255, 255, 255), True)
    p = r['timer']; rounded(p, panel, 20, acc, 2); txt('TIMER (Time Challenge)', p.x+22, p.y+14, font, acc)
    for i, rc in enumerate(r['timers']): button(rc, str(time_options[i]), (20, 150, 100) if timer_choice == i else (0, 75, 135), True, small)
    p = r['mode']; rounded(p, panel, 20, acc, 2); txt('GAME MODE', p.x+22, p.y+14, font, acc)
    for i, rc in enumerate(r['modes']): button(rc, MODES[i], (0, 145, 95) if game_mode == MODES[i] else (0, 68, 125), True, small)
    p = r['friend']; rounded(p, panel, 20, acc, 2); txt('PLAY WITH A FRIEND', p.x+22, p.y+14, font, acc)
    button(r['online'], 'ONLINE', (110, 70, 200), True, font)
    if online_on(): txt(f"Online race ready - you are P{my_turn+1}", p.x+22, p.bottom-20, tiny, (40, 150, 80))
    elif online_state == 'waiting': txt(f'Room {online_code} open - waiting for friend', p.x+22, p.bottom-20, tiny, (40, 150, 80))
    p = r['msg']; rounded(p, panel, 20, acc, 2); txt(message[:80], p.centerx, p.centery, small, (255, 255, 255), True)

def draw_menu():
    r = menu_rects(); c = r['card']; today = datetime.date.today()
    screen.blit(vgrad(c.w, c.h, (110, 190, 250), (0, 125, 235), 22), c.topleft)
    pygame.draw.rect(screen, (255, 190, 40), (c.centerx-30, c.y+36, 60, 60), border_radius=12); pygame.draw.rect(screen, (250, 245, 235), (c.centerx-24, c.y+46, 48, 44), border_radius=8)
    pygame.draw.circle(screen, (200, 195, 185), (c.centerx, c.y+68), 16); pygame.draw.polygon(screen, (255, 255, 255), _star_pts(c.centerx, c.y+68, 10))
    txt('DAILY CHALLENGE', c.centerx, c.y+128, small, (190, 225, 255), True)
    txt(f"{calendar.month_name[today.month]} {today.day}", c.centerx, c.y+164, midfont, (255, 255, 255), True)
    pygame.draw.rect(screen, (140, 205, 252), r['card_play'], border_radius=23)
    txt('Start', r['card_play'].centerx, r['card_play'].centery, font, (255, 255, 255), True)
    txt('Arrow Puzzle', 260, 400, titlefont, (44, 62, 90), True)
    lv = saved_start()[0]
    if lv > 1: pill(r['new'], f'Continue  -  Level {lv}', f"{game_mode}   -   Best {best_score}")
    else: pill(r['new'], 'New Game', f"{game_mode}   -   Best {best_score}")
    if 'resume' in r: pill(r['resume'], f'Resume  -  Level {level}', None, (255, 255, 255), BLUE, font, BLUE)
    if 'restart' in r: pill(r['restart'], 'Restart from Level 1', None, (255, 255, 255), (220, 60, 70), small, (220, 60, 70))
    draw_home_panels()

def draw_trophy_simple(cx, cy):
    dark = (18, 48, 78); mid = (40, 110, 150)
    for sg in (-1, 1): pygame.draw.ellipse(screen, dark, pygame.Rect(cx+sg*64-20, cy-44, 40, 52), 6)
    pygame.draw.polygon(screen, dark, [(cx-52, cy-60), (cx+52, cy-60), (cx+44, cy-8), (cx+20, cy+16), (cx-20, cy+16), (cx-44, cy-8)])
    pygame.draw.polygon(screen, mid, [(cx-42, cy-54), (cx-26, cy-54), (cx-32, cy-8), (cx-16, cy+10), (cx-20, cy+10), (cx-36, cy-8)])
    pygame.draw.rect(screen, dark, (cx-9, cy+16, 18, 26)); pygame.draw.rect(screen, dark, (cx-34, cy+40, 68, 14), border_radius=5); pygame.draw.rect(screen, (10, 28, 48), (cx-46, cy+54, 92, 14), border_radius=5)

DAILY_PLAY = pygame.Rect(COL_L, 650, COL_W, 60)

def daily_cells():
    today = datetime.date.today(); y, m = today.year, today.month; cw = COL_W/7; out = []
    for r_, week in enumerate(calendar.Calendar(firstweekday=6).monthdayscalendar(y, m)):
        for i, d in enumerate(week):
            if d: out.append((datetime.date(y, m, d), int(COL_L+(i+0.5)*cw), 360+r_*48))
    return out

def draw_daily():
    today = datetime.date.today(); y, m = today.year, today.month; sel = daily_date or today
    screen.blit(vgrad(VW, 230, (28, 118, 235), (75, 165, 248)), (0, 0))
    txt('Daily Challenges', VW//2, 26, midfont, (255, 255, 255), True); draw_trophy_simple(VW//2, 118)
    ndays = calendar.monthrange(y, m)[1]; got = sum(1 for d in range(1, ndays+1) if datetime.date(y, m, d).isoformat() in daily_done)
    txt(f'{calendar.month_name[m]} {y}', COL_L, 262, midfont, (30, 40, 60))
    pygame.draw.circle(screen, (255, 190, 40), (COL_L+COL_W-86, 278), 15); pygame.draw.polygon(screen, (255, 140, 20), _star_pts(COL_L+COL_W-86, 278, 9))
    s = midfont.render(f'{got}/{ndays}', True, (30, 40, 60)); screen.blit(s, (COL_L+COL_W-s.get_width(), 262))
    cw = COL_W/7
    for i, ch in enumerate('SMTWTFS'): txt(ch, COL_L+(i+0.5)*cw, 316, small, (170, 178, 190), True)
    for dt_, cx, cy in daily_cells():
        d = dt_.day; done = dt_.isoformat() in daily_done
        if done: pygame.draw.circle(screen, (255, 190, 40), (cx, cy), 22); txt(d, cx, cy, daysfont, (255, 255, 255), True)
        elif dt_ == sel: pygame.draw.circle(screen, BLUE, (cx, cy), 24); txt(d, cx, cy, daysfont, (255, 255, 255), True)
        elif dt_ == today: pygame.draw.circle(screen, BLUE, (cx, cy), 23, 3); txt(d, cx, cy, daysfont, BLUE, True)
        else: txt(d, cx, cy, daysfont, (45, 55, 80) if dt_ < today else (200, 206, 216), True)
        if dt_ == sel and done: pygame.draw.circle(screen, BLUE, (cx, cy), 26, 3)
    if sel == today: label = 'Play again' if today.isoformat() in daily_done else 'Start'
    else: label = f'{"Replay" if sel.isoformat() in daily_done else "Play"} {calendar.month_name[sel.month]} {sel.day}'
    pill(DAILY_PLAY, label)

me_sub = None            # None = the Me menu; otherwise 'awards','achievements','settings','help','about','rights','prefs','ads'
confirm_clear = False
ME_BG = (231, 237, 243)
SY = 40                  # settings page is shifted down for the header bar
ME_BACK = pygame.Rect(10, 8, 120, 54)
PREF_BTN = pygame.Rect(COL_L, 330, COL_W, 64)
rowfont = pygame.font.SysFont('arial', 26)
bodyfont = pygame.font.SysFont('arial', 19)

def goto_settings():
    global page
    page = 'menu'          # the online / mode controls now live on the home page

def txt_l(s, x, cy, f, color):
    surf = f.render(str(s), True, color); screen.blit(surf, (int(x), int(cy-surf.get_height()/2)))

def wrap_text(s, f, width):
    out = []; line = ''
    for w in s.split():
        t_ = (line+' '+w).strip()
        if f.size(t_)[0] <= width: line = t_
        else: out.append(line); line = w
    if line: out.append(line)
    return out

def me_rows():
    return {'awards': pygame.Rect(COL_L, 92, COL_W, 100), 'achievements': pygame.Rect(COL_L, 204, COL_W, 100),
            'settings': pygame.Rect(COL_L, 330, COL_W, 56),
            'help': pygame.Rect(COL_L, 410, COL_W, 56), 'about': pygame.Rect(COL_L, 466, COL_W, 56),
            'rights': pygame.Rect(COL_L, 522, COL_W, 56), 'prefs': pygame.Rect(COL_L, 578, COL_W, 56),
            'ads': pygame.Rect(COL_L, 658, COL_W, 56)}

def settings_rects():
    card = pygame.Rect(COL_L, 100, COL_W, 240)
    rows = [pygame.Rect(card.x, card.y+i*80, card.w, 80) for i in range(3)]
    return {'card': card, 'rows': rows, 'toggles': [pygame.Rect(card.right-100, rw.centery-20, 72, 40) for rw in rows]}

def me_header(label):
    pygame.draw.rect(screen, (255, 255, 255), (0, 0, VW, 70)); pygame.draw.line(screen, (222, 227, 235), (0, 70), (VW, 70), 2)
    txt(label, VW//2, 34, midfont, (30, 40, 60), True)
    if me_sub:
        pygame.draw.lines(screen, (60, 70, 90), False, [(40, 22), (28, 35), (40, 48)], 4); txt('Back', 56, 25, small, (60, 70, 90))

def chevron(cx, cy):
    pygame.draw.lines(screen, (175, 182, 195), False, [(cx-5, cy-9), (cx+5, cy), (cx-5, cy+9)], 3)

def mini_trophy(cx, cy, col):
    dark = tuple(int(c*0.78) for c in col)
    for sg in (-1, 1): pygame.draw.ellipse(screen, dark, pygame.Rect(cx+sg*15-6, cy-15, 12, 16), 3)
    pygame.draw.polygon(screen, col, [(cx-14, cy-17), (cx+14, cy-17), (cx+11, cy+1), (cx+5, cy+8), (cx-5, cy+8), (cx-11, cy+1)])
    pygame.draw.rect(screen, dark, (cx-3, cy+8, 6, 8)); pygame.draw.rect(screen, col, (cx-10, cy+16, 20, 6), border_radius=2)
    pygame.draw.polygon(screen, (255, 255, 255), _star_pts(cx, cy-6, 6))

def mini_pad(cx, cy):
    g = (122, 190, 38)
    pygame.draw.rect(screen, g, (cx-24, cy-13, 48, 28), border_radius=13)
    for sg in (-1, 1): pygame.draw.circle(screen, g, (cx+sg*15, cy+10), 9)
    pygame.draw.line(screen, (255, 255, 255), (cx-16, cy-3), (cx-6, cy-3), 3); pygame.draw.line(screen, (255, 255, 255), (cx-11, cy-8), (cx-11, cy+2), 3)
    pygame.draw.circle(screen, (255, 255, 255), (cx+10, cy-7), 2); pygame.draw.circle(screen, (255, 255, 255), (cx+16, cy-2), 2); pygame.draw.circle(screen, (255, 255, 255), (cx+10, cy+3), 2)

def me_tile(kind, cx, cy):
    cols = {'settings': (47, 128, 237), 'help': (46, 196, 102), 'about': (47, 128, 237), 'rights': (92, 80, 205), 'prefs': (20, 184, 200), 'ads': (240, 64, 52)}
    c = cols[kind]; W = (255, 255, 255)
    pygame.draw.rect(screen, c, (cx-20, cy-20, 40, 40), border_radius=10)
    if kind == 'settings':
        for k in range(8):
            a = k*math.pi/4; pygame.draw.line(screen, W, (cx+8*math.cos(a), cy+8*math.sin(a)), (cx+13*math.cos(a), cy+13*math.sin(a)), 4)
        pygame.draw.circle(screen, W, (cx, cy), 10); pygame.draw.circle(screen, c, (cx, cy), 4)
    elif kind in ('help', 'about'):
        pygame.draw.circle(screen, W, (cx, cy), 13); txt('?' if kind == 'help' else 'i', cx, cy, font, c, True)
    elif kind == 'rights':
        pygame.draw.rect(screen, W, (cx-10, cy-13, 20, 26), border_radius=4); pygame.draw.rect(screen, c, (cx-5, cy-16, 10, 6), border_radius=2)
        pygame.draw.lines(screen, c, False, [(cx-5, cy+2), (cx-1, cy+7), (cx+6, cy-3)], 3)
    elif kind == 'prefs':
        pygame.draw.circle(screen, W, (cx-3, cy-6), 6); pygame.draw.ellipse(screen, W, (cx-13, cy+1, 20, 13))
        pygame.draw.circle(screen, c, (cx+8, cy+8), 8); pygame.draw.circle(screen, W, (cx+8, cy+8), 7)
        pygame.draw.lines(screen, c, False, [(cx+5, cy+8), (cx+7, cy+10), (cx+11, cy+5)], 2)
    elif kind == 'ads':
        pygame.draw.circle(screen, W, (cx, cy), 13, 2); txt('Ad', cx, cy, tiny, W, True)

def draw_me_main():
    screen.fill(ME_BG); me_header('Me'); r = me_rows(); W = (255, 255, 255); DK = (20, 24, 40)
    for key, label in (('awards', 'Awards'), ('achievements', 'Achievements')):
        rc = r[key]; pygame.draw.rect(screen, W, rc, border_radius=22); cx, cy = rc.x+66, rc.centery
        pygame.draw.circle(screen, (214, 232, 250) if key == 'awards' else (238, 244, 225), (cx, cy), 36)
        if key == 'awards': mini_trophy(cx, cy-2, (240, 180, 30))
        else: mini_pad(cx, cy)
        txt_l(label, rc.x+130, rc.centery, rowfont, DK); chevron(rc.right-30, rc.centery)
    for key, label in (('settings', 'Settings'),):
        rc = r[key]; pygame.draw.rect(screen, W, rc, border_radius=16); me_tile(key, rc.x+34, rc.centery); txt_l(label, rc.x+80, rc.centery, rowfont, DK); chevron(rc.right-30, rc.centery)
    grp = pygame.Rect(COL_L, 410, COL_W, 224); pygame.draw.rect(screen, W, grp, border_radius=16)
    for key, label in (('help', 'Help'), ('about', 'About Game'), ('rights', 'Privacy Rights'), ('prefs', 'Privacy Preferences')):
        rc = r[key]; me_tile(key, rc.x+34, rc.centery); txt_l(label, rc.x+80, rc.centery, rowfont, DK); chevron(rc.right-30, rc.centery)
        if key != 'prefs': pygame.draw.line(screen, (222, 227, 235), (rc.x+80, rc.bottom), (rc.right, rc.bottom), 1)
    rc = r['ads']; pygame.draw.rect(screen, W, rc, border_radius=16); me_tile('ads', rc.x+34, rc.centery); txt_l('Remove Ads', rc.x+80, rc.centery, rowfont, DK)

def goal_row(y, name, desc, val, goal, col, star=False):
    rc = pygame.Rect(350, y, 580, 76); done = val >= goal
    pygame.draw.rect(screen, (255, 255, 255), rc, border_radius=16)
    cx, cy = rc.x+44, rc.centery; pygame.draw.circle(screen, (255, 241, 205) if done else (232, 235, 240), (cx, cy), 28)
    c = col if done else (170, 176, 188)
    if star: pygame.draw.polygon(screen, c, _star_pts(cx, cy, 17))
    else: mini_trophy(cx, cy-2, c)
    txt_l(name, rc.x+92, rc.y+25, font, (20, 24, 40)); txt_l(desc, rc.x+92, rc.y+52, small, (120, 130, 150))
    s = 'Done!' if done else f'{min(val, goal)}/{goal}'; txt_l(s, rc.right-24-font.size(s)[0], rc.y+24, font, (46, 170, 90) if done else (90, 100, 120))
    pygame.draw.rect(screen, (225, 230, 238), (rc.right-164, rc.y+46, 140, 8), border_radius=4)
    w = int(140*min(1, val/goal))
    if w > 1: pygame.draw.rect(screen, (46, 190, 100) if done else (47, 128, 237), (rc.right-164, rc.y+46, w, 8), border_radius=4)

def text_card(paras):
    lines = []
    for p in paras: lines += wrap_text(p, bodyfont, 540) + ['']
    h = 30+28*len(lines); pygame.draw.rect(screen, (255, 255, 255), (350, 96, 580, h), border_radius=16)
    for i, l in enumerate(lines): txt(l, 370, 118+i*28, bodyfont, (40, 48, 70))

def draw_toggle(rc, on):
    pygame.draw.rect(screen, BLUE if on else (221, 227, 234), rc, border_radius=rc.h//2)
    kx = rc.right-rc.h//2 if on else rc.x+rc.h//2
    pygame.draw.circle(screen, (205, 212, 222), (kx, rc.centery+2), rc.h//2-3)
    pygame.draw.circle(screen, (255, 255, 255), (kx, rc.centery), rc.h//2-4)

def draw_me_settings():
    screen.fill(ME_BG); me_header('Settings'); r = settings_rects()
    pygame.draw.rect(screen, (255, 255, 255), r['card'], border_radius=22)
    for i, (label, on) in enumerate((('Sounds', sound_on), ('Vibration', vibe_on), ('Auto-Lock', autolock_on))):
        rw = r['rows'][i]; txt_l(label, rw.x+30, rw.centery, rowfont, (20, 24, 40)); draw_toggle(r['toggles'][i], on)
        if i < 2: pygame.draw.line(screen, (222, 227, 235), (rw.x+30, rw.bottom), (rw.right, rw.bottom), 1)

def toggle_setting(i):
    global sound_on, vibe_on, autolock_on
    if i == 0:
        sound_on = not sound_on
        if not sound_on: pygame.mixer.stop()
        else: play_sfx('click')
    elif i == 1:
        vibe_on = not vibe_on
        if vibe_on: buzz()
    else: autolock_on = not autolock_on; touch()
    save_data()

def draw_me():
    if me_sub is None: draw_me_main(); return
    if me_sub == 'settings': draw_me_settings(); return
    titles = {'awards': 'Awards', 'achievements': 'Achievements', 'help': 'Help', 'about': 'About Game', 'rights': 'Privacy Rights', 'prefs': 'Privacy Preferences', 'ads': 'Remove Ads'}
    screen.fill(ME_BG); me_header(titles[me_sub])
    if me_sub == 'awards':
        tiers = [('Bronze Cup', 500, (205, 127, 50)), ('Silver Cup', 1500, (170, 178, 190)), ('Gold Cup', 3000, (240, 180, 30)),
                 ('Platinum Cup', 5000, (110, 190, 230)), ('Diamond Cup', 8000, (90, 150, 255)), ('Legend Cup', 12000, (200, 90, 230))]
        for i, (n, g, c) in enumerate(tiers): goal_row(90+i*88, n, f'Reach a best score of {g}', best_score, g, c)
    elif me_sub == 'achievements':
        gold = (240, 180, 30)
        items = [('First Steps', 'Reach level 2', max_level, 2), ('Puzzle Pro', 'Reach level 5', max_level, 5), ('Arrow Master', 'Reach level 10', max_level, 10),
                 ('Daily Player', 'Finish a Daily Challenge', len(daily_done), 1), ('Streak Star', 'Daily streak of 3 days', streak, 3), ('Battle Winner', 'Win an online race', battle_wins, 1)]
        for i, (n, d, v, g) in enumerate(items): goal_row(90+i*88, n, d, v, g, gold, True)
    elif me_sub == 'help':
        text_card(['Tap an arrow that has a clear straight path to the edge of the board. It slides out and you score 10 points.',
                   'Tap a blocked arrow and you lose a life. Lose all your lives and the level restarts.',
                   'Clear every arrow to finish the level (+50 bonus). Every level has a new shape.',
                   'HINT, WIND, ERASER, UNDO and RESET help when you are stuck, but they cost points and are limited per level.',
                   'Online race: you and your friend get the SAME puzzle at the same time. The first one to clear every arrow wins!'])
    elif me_sub == 'about':
        text_card([f'Arrow Puzzle {VERSION}', 'Made with Python + Pygame.', 'Modes: Classic, Time Challenge, Daily Challenge and Friends Battle (take turns on one screen, or race a friend online).', f'Your best score: {best_score}'])
    elif me_sub == 'rights':
        text_card(['Your scores, streak and daily progress are saved only on this device, in the file arrow_puzzle_scores.json.',
                   'In an online race the game only shares your moves and progress with your friend through the relay server. No personal information is collected.'])
    elif me_sub == 'prefs':
        text_card(['Everything the game remembers (best score, top scores, streak, daily calendar, awards) lives on this device.',
                   'You can erase all of it below. This cannot be undone.'])
        pill(PREF_BTN, 'Tap again to confirm' if confirm_clear else 'Clear saved data', None, (220, 60, 70))
    elif me_sub == 'ads':
        text_card(['Good news - Arrow Puzzle has no ads, so there is nothing to remove. Enjoy the game!'])

def clear_all_data():
    global best_score, top_scores, streak, last_daily, max_level, battle_wins
    best_score = 0; top_scores = []; streak = 0; last_daily = ''; max_level = 1; battle_wins = 0; daily_done.clear(); save_data(); say('Saved data cleared.')

def draw_pages():
    t = THEMES[theme_index]; screen.fill(t['bg'] if page in ('me', 'menu') else (250, 252, 255))
    {'menu': draw_menu, 'daily': draw_daily, 'me': draw_me}[page]()
    draw_tab_bar()
    if online_modal: _dim(170); draw_modal(draw_online_box)
    present()

def _online_busy(): return online_state in ('connected', 'waiting', 'connecting')

def play_daily(d=None):
    global page,daily_date,daily_complete
    daily_date = d or datetime.date.today(); daily_complete = False
    if _online_busy(): goto_settings(); say('Leave the online room first (ONLINE button).'); return
    show_loading('LOADING DAILY CHALLENGE...'); change_mode('Daily Challenge'); start_game(); page = 'game'

def play_new(fresh=False):
    global page
    if online_on(): page = 'game'; on_start(); return
    if _online_busy(): goto_settings(); say('Leave the online room first (ONLINE button).'); return
    show_loading('LOADING...')
    if game_mode == 'Daily Challenge': change_mode('Classic')
    start_game(fresh=fresh); page = 'game'

def page_click(pos):
    global page, theme_index, me_sub, confirm_clear, daily_date
    for i, (k, _) in enumerate(TABS):
        if tab_rect(i).collidepoint(pos):
            page = k; play_sfx('click')
            if k == 'me': me_sub = None; confirm_clear = False
            return
    if page == 'menu':
        r = menu_rects()
        if r['card'].collidepoint(pos): play_daily()
        elif r['new'].collidepoint(pos): play_new()
        elif 'resume' in r and r['resume'].collidepoint(pos): page = 'game'; play_sfx('click')
        elif 'restart' in r and r['restart'].collidepoint(pos): play_new(fresh=True)
        else:
            h = home_rects()
            for i, c in enumerate(h['themes']):
                if math.hypot(pos[0]-c[0], pos[1]-c[1]) <= 24: theme_index = i; play_sfx('click'); save_data()
            for i, rc in enumerate(h['timers']):
                if rc.collidepoint(pos): set_timer(i); save_data()
            for i, rc in enumerate(h['modes']):
                if rc.collidepoint(pos): change_mode(MODES[i])
            if h['online'].collidepoint(pos): open_online()
    elif page == 'daily':
        if DAILY_PLAY.collidepoint(pos): play_daily(daily_date)
        else:
            for dt_, cx, cy in daily_cells():
                if math.hypot(pos[0]-cx, pos[1]-cy) <= 26:
                    if dt_ > datetime.date.today(): say('This day is not open yet'); play_sfx('click')
                    else: daily_date = dt_; play_sfx('click')
    elif page == 'me':
        if me_sub is None:
            for k, rc in me_rows().items():
                if rc.collidepoint(pos): me_sub = k; confirm_clear = False; play_sfx('click'); return
        elif ME_BACK.collidepoint(pos): me_sub = None; confirm_clear = False; play_sfx('click')
        elif me_sub == 'settings':
            r = settings_rects()
            for i, rw in enumerate(r['rows']):
                if rw.collidepoint(pos): toggle_setting(i)
        elif me_sub == 'prefs' and PREF_BTN.collidepoint(pos):
            if confirm_clear: clear_all_data(); confirm_clear = False
            else: confirm_clear = True; play_sfx('click')


def main():
    global page,intro_open_t,hint_until,awaiting_next,pause_start,box_open_t,playing,theme_index,time_left,hint_index,eraser_mode,board,score,lives,level,game_start_ms,history,moving,next_level_at,turn,bs,bl
    load_data();board=new_board();running=True;last_now=pygame.time.get_ticks();was_playing=False
    while running:
        clock.tick(60); now=pygame.time.get_ticks(); dt=now-last_now; last_now=now
        if page!='game' and not online_on():          # the game is paused while you are on another page
            game_start_ms+=dt; box_open_t+=dt; intro_open_t+=dt; pause_start+=dt
            if next_level_at: next_level_at+=dt
            if hint_until: hint_until+=dt
        if online_on() and playing and not was_playing and page!='game': page='game'
        was_playing=playing
        if playing and not awaiting_next and not retry_box and not intro_box:
            if race_start and now<race_start: game_start_ms=race_start
            elapsed=max(0,(now-game_start_ms)//1000)
            if game_mode=='Time Challenge':
                time_left=max(0,time_options[timer_choice]-elapsed)
                if time_left<=0: playing=False; record_score(); play_sfx('lose'); show_retry("TIME'S UP!"); say(f'TIME IS UP! Level {level} restarts.')
            else: time_left=elapsed
        for item in pending[:]:
            if now>=item[0]: pending.remove(item); item[1]()
        if next_level_at and now>=next_level_at:
            next_level_at=None; go_next_level()          # no pop-up: the next level appears straight away
        if awaiting_next and now-box_open_t>=AUTO_MS: go_next_level()
        if intro_box and now-intro_open_t>=INTRO_MS: dismiss_intro()
        if autolock_on and page=='game' and playing and not online_on() and now-last_input_ms>AUTOLOCK_MS:
            page='menu'; save_progress(); say('Auto-locked after 1 minute of no activity')
        net_poll()
        draw()
        for e in pygame.event.get():
            if e.type in (pygame.MOUSEBUTTONDOWN,pygame.KEYDOWN): touch()
            if e.type==pygame.QUIT:running=False
            elif e.type==pygame.KEYDOWN and online_modal:online_key(e)
            elif e.type==pygame.KEYDOWN and e.key==pygame.K_ESCAPE:running=not esc_quit()
            elif e.type==pygame.KEYDOWN and e.key==pygame.K_F11:set_display(not fullscreen_on)
            elif e.type==pygame.KEYDOWN and e.key in (pygame.K_RETURN,pygame.K_SPACE) and daily_complete:close_daily_complete()
            elif e.type==pygame.KEYDOWN and e.key in (pygame.K_RETURN,pygame.K_SPACE) and intro_box:dismiss_intro()
            elif e.type==pygame.KEYDOWN and e.key in (pygame.K_RETURN,pygame.K_SPACE) and awaiting_next:go_next_level()
            elif e.type==pygame.KEYDOWN and e.key in (pygame.K_RETURN,pygame.K_SPACE) and retry_box:retry_level()
            elif e.type==pygame.MOUSEBUTTONDOWN and e.button==1:
                pos=to_virtual(e.pos);b=buttons()
                mpos=(pos[0]-OX,pos[1])                    # pop-ups are drawn on a 1000-wide sheet in the middle
                if online_modal:
                    online_click(mpos); continue
                if page!='game':
                    page_click(pos); continue
                if daily_complete:
                    if pygame.Rect(370,515,260,40).collidepoint(mpos): close_daily_complete()
                    continue
                if race_result:
                    if online_on() and online_role=='host' and RB_REMATCH.collidepoint(mpos): host_start_online()
                    elif RB_LEAVE.collidepoint(mpos): net_close(); page='menu'; say('Left the online room.')
                    continue
                if intro_box:
                    dismiss_intro(); continue
                if retry_box:
                    if BTN_NEXT.collidepoint(mpos) or b['start'].collidepoint(pos): retry_level()
                    continue
                if awaiting_next:
                    if BTN_NEXT.collidepoint(mpos): go_next_level()
                    continue
                if b['back'].collidepoint(pos): page='menu'; save_progress(); play_sfx('click')
                elif b['start'].collidepoint(pos):on_start()
                elif b['hint'].collidepoint(pos) and playing:guard(do_hint)
                elif b['wind'].collidepoint(pos) and playing:guard(do_wind)
                elif b['eraser'].collidepoint(pos) and playing:guard(do_eraser)
                elif b['undo'].collidepoint(pos) and playing:guard(do_undo)
                elif b['reset'].collidepoint(pos) and playing:guard(do_reset)
                elif CLIP.collidepoint(pos) and playing:
                        idx=hit_arrow(pos)
                        if idx is not None:board_tap(idx)
    save_progress(); save_data()
    net_close()
    pygame.quit()

if __name__=='__main__':main()
