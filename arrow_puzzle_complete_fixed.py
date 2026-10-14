import pygame, random, math, json, datetime, subprocess, sys, wave
import numpy as np
from pathlib import Path

# Arrow Puzzle - fully packed grid, snake-style escape animation, working modes/themes
# Install once: python -m pip install pygame numpy
# Run: python arrow_puzzle_complete_fixed.py
pygame.init()
SFX = {}
combo = 0
finale_start = 0
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
    snd = SFX.get(name)
    if snd is not None:
        try: snd.play()
        except pygame.error: pass

def play_celebration(): play_sfx('win')

def schedule(delay_ms, fn): pending.append((pygame.time.get_ticks()+delay_ms, fn))

def game_finale():
    """Game finished: Diwali crackers, bombs and rockets + fireworks on screen."""
    global finale_start
    finale_start = pygame.time.get_ticks(); play_sfx('diwali'); fx_start('diwali')

# ---- Window: everything is drawn on a fixed 1000x800 canvas and scaled to the window,
# ---- so mouse clicks always hit the right buttons even if the window is resized.
VW, VH = 1000, 800
window = pygame.display.set_mode((VW, VH), pygame.RESIZABLE)
VERSION = 'v8'
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
    win.fill((20, 24, 36))
    if (sw, sh) == (VW, VH): win.blit(screen, view_off)
    else: win.blit(pygame.transform.smoothscale(screen, (sw, sh)), view_off)
    pygame.display.flip()

def to_virtual(pos):
    return (int((pos[0] - view_off[0]) / view_scale), int((pos[1] - view_off[1]) / view_scale))

BOARD = pygame.Rect(300, 215, 470, 455)
SLIDE_SPEED = 1.0   # pixels per millisecond when an arrow escapes
CLIP = BOARD.inflate(22, 22)
BOARD_SPAN = 430    # grid width/height in pixels (cell size shrinks as the grid grows)
EXT_FRAC = 0.42     # arrows are stretched half a cell past their end cells -> no empty gaps
COLS = ROWS = 8; CELL = 57; LINE_W = 8; HEAD_LEN = 24; HEAD_W = 28; CORNER_R = 23; EXT = 22
ORIGIN = (0, 0); LENGTHS = [2, 3, 4]

def grid_size_for(lv):
    """Dense from the start: level 1 = 12x12 (~40 arrows); +1 row/col every level up to 22x22 (~110 arrows)."""
    return min(22, 11 + lv)

def lengths_for(lv):
    # early levels have short arrows; later levels drop the 2-cell ones and add long winding ones
    # many short arrows keep the board packed; deeper levels add long winding ones
    return [2,2,2,3,3,3,4,4,5,6,7] + [9,11,13]*(lv//5)

def set_grid(lv):
    global COLS,ROWS,CELL,LINE_W,HEAD_LEN,HEAD_W,CORNER_R,EXT,ORIGIN,LENGTHS
    COLS = ROWS = grid_size_for(lv)
    CELL = BOARD_SPAN / (COLS - 1)
    LINE_W = max(3, round(CELL * 0.16)); HEAD_LEN = round(CELL * 0.46); HEAD_W = round(CELL * 0.56)
    CORNER_R = CELL * 0.4; EXT = CELL * EXT_FRAC
    ORIGIN = (BOARD.centerx - (COLS - 1) * CELL / 2, BOARD.centery - (ROWS - 1) * CELL / 2)
    LENGTHS = lengths_for(lv)

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
best_score=0; top_scores=[]; streak=0; last_daily=''
moving={}; flash={}; next_level_at=None
awaiting_next=False; pause_start=0; box_open_t=0
hint_until=0; game_started=False; retry_box=None; level_start_score=0; board_backup=[]; AUTO_MS=5500
COST={'hint':15,'wind':25,'eraser':20,'undo':10,'reset':20}     # points paid for every help

def lives_for(lv): return 3 if lv<=5 else 2
def charges_for(lv):
    """How many times each help can be used per level. Deeper levels give fewer helps."""
    return {'hint':max(1,2-lv//4),'wind':1 if lv<=8 else 0,'eraser':1 if lv<=5 else 0,'undo':max(1,2-lv//4),'reset':1}
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
    uses=charges_for(level); snapshot_level()
# Friends Battle state
turn=0; bs=[0,0]; bl=[3,3]
MODES=['Classic','Time Challenge','Daily Challenge','Friends Battle']

DIR_VECTORS={'right':(1,0),'left':(-1,0),'up':(0,-1),'down':(0,1)}
VEC_TO_DIR={v:k for k,v in DIR_VECTORS.items()}
DIRS=list(DIR_VECTORS.values())

def load_data():
    global best_score, top_scores, streak, last_daily
    try:
        d=json.loads(SAVE_FILE.read_text())
        best_score=int(d.get('best',0)); top_scores=d.get('top',[]); streak=int(d.get('streak',0)); last_daily=d.get('last_daily','')
    except Exception: pass

def save_data():
    try: SAVE_FILE.write_text(json.dumps({'best':best_score,'top':top_scores[:5],'streak':streak,'last_daily':last_daily}))
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
      'start':pygame.Rect(300,125,125,48),'hint':pygame.Rect(435,125,92,48),'wind':pygame.Rect(537,125,92,48),
      'eraser':pygame.Rect(639,125,92,48),'undo':pygame.Rect(741,125,92,48),'reset':pygame.Rect(843,125,92,48),
      'theme':pygame.Rect(820,322,150,35),'timer30':pygame.Rect(820,410,35,30),'timer60':pygame.Rect(859,410,35,30),
      'timer90':pygame.Rect(898,410,35,30),'timer120':pygame.Rect(937,410,35,30),
      'leftmode':pygame.Rect(24,670,35,35),'rightmode':pygame.Rect(229,670,35,35),
      **{f'mode{i}':pygame.Rect(820,500+i*38,150,32) for i in range(4)}}

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

def inb(c): return 0<=c[0]<COLS and 0<=c[1]<ROWS

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
    order=[(c,r) for c in range(COLS) for r in range(ROWS)]; rng.shuffle(order)
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
    tries=min(10,3+lv); best=None; bestk=(True,0,10**9)
    attempts=0
    while attempts<tries*40 or (best is None and attempts<6000):
        attempts+=1
        paths=make_partition(rng)
        if paths is None: continue
        arrows=orient_paths(paths,rng)
        if not arrows: continue
        k=(len(arrows)<COLS*ROWS/(3.5+0.08*lv), -waves(arrows), free_count(arrows)/len(arrows))
        if k<bestk: best,bestk=arrows,k
        tries-=1
        if tries<=0: break
    return best or []

def new_board():
    seed=int(datetime.date.today().strftime('%Y%m%d'))*100+level if game_mode=='Daily Challenge' else None
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
    today=datetime.date.today()
    if last_daily==today.isoformat(): return
    streak=streak+1 if last_daily==(today-datetime.timedelta(days=1)).isoformat() else 1
    last_daily=today.isoformat(); save_data()

def start_game():
    """Brand-new game from level 1."""
    global board,score,lives,level,time_left,playing,history,hint_index,eraser_mode,game_start_ms,moving,flash,next_level_at,turn,bs,bl,awaiting_next,combo,game_started,retry_box
    combo=0; pending.clear(); fx_stop(); play_sfx('click'); awaiting_next=False; retry_box=None; score,level=0,1; lives=lives_for(1); playing=True; game_started=True; turn=0; bs=[0,0]; bl=[3,3]
    history=[];hint_index=None;eraser_mode=False;moving={};flash={};next_level_at=None
    game_start_ms=pygame.time.get_ticks()
    time_left=time_options[timer_choice] if game_mode=='Time Challenge' else 0
    board=new_board(); begin_level()
    say('P1 starts! Pick a free arrow.' if battle() else 'Find an arrow with a clear path to the edge!')

def retry_level():
    """Out of lives / time up: replay the SAME level (never go back to level 1)."""
    global board,score,lives,time_left,playing,history,hint_index,eraser_mode,game_start_ms,moving,flash,next_level_at,awaiting_next,combo,retry_box,uses,turn,bs,bl
    combo=0; pending.clear(); fx_stop(); play_sfx('click'); awaiting_next=False; retry_box=None; next_level_at=None
    score=level_start_score; lives=lives_for(level); playing=True; history=[]; hint_index=None; eraser_mode=False; moving={}; flash={}
    board=[dict(c,points=list(c['points']),cells=list(c['cells']),removed=False) for c in board_backup]
    uses=charges_for(level); game_start_ms=pygame.time.get_ticks(); turn=0; bs=[0,0]; bl=[lives,lives]
    time_left=time_options[timer_choice] if game_mode=='Time Challenge' else 0
    say(f'LEVEL {level} - try again!')

def on_start():
    if game_started: retry_level()
    else: start_game()

def show_retry(title):
    global retry_box
    retry_box=title

def change_mode(m):
    global combo,level,awaiting_next,game_mode,playing,board,history,moving,flash,hint_index,eraser_mode,time_left,next_level_at,game_started,retry_box,score
    play_sfx('click'); combo=0; level=1; awaiting_next=False; game_mode=m; playing=False; history=[]; moving={}; flash={}; hint_index=None; eraser_mode=False; next_level_at=None
    time_left=time_options[timer_choice] if m=='Time Challenge' else 0
    board=new_board(); game_started=False; retry_box=None; fx_stop(); score=0; begin_level()
    hints={'Classic':'no time limit','Time Challenge':'beat the clock','Daily Challenge':'same puzzle for everyone today','Friends Battle':'2 players, take turns'}
    say(f'MODE: {m} ({hints[m]}) - press START')

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

def after_move():
    global board,level,score,hint_index,eraser_mode,playing,next_level_at
    hint_index=None; eraser_mode=False
    if all(c['removed'] for c in board):
        if battle():
            store_turn(); playing=False; game_finale()
            say('P1 WINS!' if bs[0]>bs[1] else 'P2 WINS!' if bs[1]>bs[0] else "IT'S A DRAW!")
            return
        score+=50
        if game_mode=='Daily Challenge':
            playing=False; update_streak(); record_score(); game_finale(); say('DAILY CHALLENGE CLEARED! +50 BONUS')
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
        if battle() and not all(c['removed'] for c in board):
            switch_turn(); say(f'ARROW ESCAPED! P{turn+1}, your turn')
        after_move()
    else:
        combo=0;lives-=1;hint_index=None;flash[index]=pygame.time.get_ticks()
        if lives<=0:
            playing=False; play_sfx('blocked')
            if battle():
                store_turn(); say(f'P{turn+1} IS OUT OF LIVES - P{2-turn} WINS!'); schedule(900,game_finale)
            else:
                record_score(); say(f'OUT OF LIVES! Level {level} will restart - not level 1')
                schedule(800,lambda:(play_sfx('lose'),show_retry('OUT OF LIVES!')))
        else:
            play_sfx('blocked'); say('BLOCKED PATH! Try another arrow.')
            if battle(): switch_turn(); say(f'BLOCKED! P{turn+1}, your turn')

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
    for c in range(COLS):
        for r in range(ROWS):
            x,y=cell_to_px((c,r)); pygame.draw.circle(screen,color,(int(x),int(y)),3)

def draw():
    t=THEMES[theme_index]; acc=t['accent']; panel=t['panel']; screen.fill(t['bg']); b=buttons()
    txt('ARROW',430,25,title,(230,157,44),True);txt('PUZZLE',570,25,title,(0,160,195),True)
    txt(f'PYTHON + PYGAME EDITION  ({VERSION})',500,72,small,(0,105,135),True)
    can=lambda k: playing and uses.get(k,0)>0
    button(b['start'],'START' if not game_started else f'RETRY L{level}',(16,155,75),icon='play');button(b['hint'],'HINT',(0,125,205),can('hint'),icon='hint')
    button(b['wind'],'WIND',(25,100,215),can('wind'),icon='wind');button(b['eraser'],'ERASER',(222,100,52) if not eraser_mode else (255,150,40),can('eraser'),icon='eraser')
    button(b['undo'],'UNDO',(0,110,145),can('undo') and bool(history),icon='undo');button(b['reset'],'RESET',(170,40,50),can('reset'),icon='reset')
    for k in ('hint','wind','eraser','undo','reset'): badge(b[k],uses.get(k,0))
    rounded(pygame.Rect(15,220,258,340),panel,20,acc,2)
    txt('♥ LIVES'+(f'  (P{turn+1})' if battle() else ''),35,237,font,acc);txt('♥ '*lives if lives else '—',38,270,font,(245,65,90))
    pygame.draw.line(screen,acc,(30,310),(255,310),2);txt('SCORE',35,326,font,(237,174,70));txt(score,62,356,title,(242,190,80))
    if battle():
        sc=bs[:]; sc[turn]=score; txt(f'P1:{sc[0]}  P2:{sc[1]}',130,330,small,(255,255,255))
    pygame.draw.line(screen,acc,(30,402),(255,402),2);txt('LEVEL',35,418,font,(70,205,125));txt(level,62,449,title,(70,205,125))
    pygame.draw.line(screen,acc,(30,495),(255,495),2);txt('TIME'+(' LEFT' if game_mode=='Time Challenge' else ''),35,508,font,acc);txt(f'{time_left}s',62,532,font,(255,255,255))
    rounded(pygame.Rect(15,578,258,130),panel,20,acc,2);txt('GAME MODE',35,590,font,acc)
    button(b['leftmode'],'‹',(0,100,180));button(b['rightmode'],'›',(0,100,180));txt(game_mode,145,687,small,(255,255,255),True)
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
    # theme panel
    rounded(pygame.Rect(812,220,173,150),panel,20,acc,2);txt('THEME',832,234,font,acc)
    for i,th in enumerate(THEMES):
        pygame.draw.circle(screen,th['circle'],(837+i*43,277),15)
        if i==theme_index:pygame.draw.circle(screen,(255,255,255),(837+i*43,277),20,3)
    button(b['theme'],t['name'],(0,85,155))
    rounded(pygame.Rect(812,382,173,75),panel,20,acc,2);txt('TIMER',832,389,font,acc)
    for key,label in [('timer30','30'),('timer60','60'),('timer90','90'),('timer120','120')]:
        button(b[key],label,(20,150,100) if time_options[timer_choice]==int(label) else (0,75,135),True,tiny)
    rounded(pygame.Rect(812,470,173,190),panel,20,acc,2);txt('GAME MODE',832,480,font,acc)
    for i,mode in enumerate(MODES):button(b[f'mode{i}'],mode,(0,145,95) if game_mode==mode else (0,68,125),True,tiny)
    rounded(pygame.Rect(295,690,502,40),panel,20,acc,2);txt(message[:58],546,710,small,(255,220,100) if message.startswith('Hint') else (255,255,255),True)
    rounded(pygame.Rect(15,742,970,45),panel,18,acc,2);txt(f'Best: {best_score}',32,755,small,(255,205,65));txt(f'Daily streak: {streak} day(s)',330,755,small,(100,220,255));txt('Top: '+', '.join(map(str,top_scores))[:38],635,755,tiny,(255,255,255))
    if awaiting_next: draw_level_box()
    elif retry_box: draw_retry_box()
    else: fx_draw()
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
            x=random.randint(80,920); y=random.randint(520,720); col=random.choice(FX_PALETTE)
            _burst(x,y,col,10,150,0.5); fx_glows.append([x,y,45,col,0.25,0.0])
        elif kind=='boom':
            x=random.randint(170,830); y=random.randint(110,400); col=random.choice(FX_PALETTE)
            _burst(x,y,col,90,300,1.0); _burst(x,y,(255,255,255),30,170,0.7); fx_glows.append([x,y,230,col,0.8,0.0]); fx_flash=1.0
        elif kind=='launch':
            fx_rockets.append({'x':random.randint(150,850),'y0':810.0,'y1':random.randint(110,330),'t0':ev[0],'t1':max(ev[2],ev[0]+300),'col':random.choice(FX_PALETTE),'trail':[]})
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
    _dim(150); fx_draw()
    rounded(pygame.Rect(300,180,400,380),(14,20,44),28,acc,4)
    screen.set_clip(pygame.Rect(312,190,376,236)); draw_trophy(500,318,t); screen.set_clip(None)
    txt(f'LEVEL {level} COMPLETE!',500,438,bigfont,(255,255,255),True)
    txt(f'+50 BONUS    SCORE {score}',500,462,small,(170,185,220),True)
    button(BTN_NEXT,f'START LEVEL {level+1}',(16,155,75),True,font)
    txt(f'Next level starts in {max(0,AUTO_MS-t)//1000+1}s',500,543,tiny,(170,185,220),True)
    pygame.draw.rect(screen,(40,52,90),(370,553,260,4),border_radius=2)
    pygame.draw.rect(screen,acc,(370,553,int(260*min(1,t/AUTO_MS)),4),border_radius=2)

def draw_retry_box():
    _dim(160); red=(225,60,80)
    rounded(pygame.Rect(300,215,400,335),(14,20,44),28,red,4)
    pygame.draw.circle(screen,red,(468,300),30); pygame.draw.circle(screen,red,(532,300),30)
    pygame.draw.polygon(screen,red,[(440,318),(560,318),(500,385)])
    pygame.draw.lines(screen,(14,20,44),False,[(500,275),(488,300),(508,318),(494,345),(500,368)],4)
    txt(retry_box,500,425,bigfont,(255,255,255),True)
    txt(f'Level {level}   Score {score}',500,455,small,(170,185,220),True)
    button(BTN_NEXT,f'RETRY LEVEL {level}',(16,155,75),True,font)

def show_loading(text):
    _dim(170); txt(text,500,400,bigfont,(255,255,255),True); present()

def go_next_level():
    global level,board,moving,flash,history,awaiting_next,game_start_ms,hint_index,lives,eraser_mode
    show_loading(f'LOADING LEVEL {level+1}...')
    level+=1; board=new_board(); now=pygame.time.get_ticks()
    game_start_ms+=now-pause_start+(10000 if game_mode=='Time Challenge' else 0)
    moving={}; flash={}; history=[]; hint_index=None; eraser_mode=False; awaiting_next=False; fx_stop()
    lives=min(lives_for(level),max(lives,1)); begin_level()
    say(f'LEVEL {level}! {len(board)} arrows - tougher, and fewer helps!')

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

def main():
    global awaiting_next,pause_start,box_open_t,playing,theme_index,time_left,hint_index,eraser_mode,board,score,lives,level,game_start_ms,history,moving,next_level_at,turn,bs,bl
    load_data();board=new_board();running=True
    while running:
        clock.tick(60); now=pygame.time.get_ticks()
        if playing and not awaiting_next and not retry_box:
            elapsed=(now-game_start_ms)//1000
            if game_mode=='Time Challenge':
                time_left=max(0,time_options[timer_choice]-elapsed)
                if time_left<=0: playing=False; record_score(); play_sfx('lose'); show_retry("TIME'S UP!"); say(f'TIME IS UP! Level {level} restarts.')
            else: time_left=elapsed
        for item in pending[:]:
            if now>=item[0]: pending.remove(item); item[1]()
        if next_level_at and now>=next_level_at:
            next_level_at=None; awaiting_next=True; pause_start=now; box_open_t=now; say(f'LEVEL {level} COMPLETE! Next level starts automatically')
        if awaiting_next and now-box_open_t>=AUTO_MS: go_next_level()
        draw()
        for e in pygame.event.get():
            if e.type==pygame.QUIT:running=False
            elif e.type==pygame.KEYDOWN and e.key==pygame.K_ESCAPE:running=False
            elif e.type==pygame.KEYDOWN and e.key in (pygame.K_RETURN,pygame.K_SPACE) and awaiting_next:go_next_level()
            elif e.type==pygame.KEYDOWN and e.key in (pygame.K_RETURN,pygame.K_SPACE) and retry_box:retry_level()
            elif e.type==pygame.MOUSEBUTTONDOWN and e.button==1:
                pos=to_virtual(e.pos);b=buttons()
                if retry_box:
                    if BTN_NEXT.collidepoint(pos) or b['start'].collidepoint(pos): retry_level()
                    continue
                if awaiting_next:
                    if BTN_NEXT.collidepoint(pos): go_next_level()
                    continue
                if b['start'].collidepoint(pos):on_start()
                elif b['hint'].collidepoint(pos) and playing:do_hint()
                elif b['wind'].collidepoint(pos) and playing:do_wind()
                elif b['eraser'].collidepoint(pos) and playing:do_eraser()
                elif b['undo'].collidepoint(pos) and playing:do_undo()
                elif b['reset'].collidepoint(pos) and playing:do_reset()
                elif b['theme'].collidepoint(pos):theme_index=(theme_index+1)%len(THEMES);play_sfx('click')
                elif any(math.hypot(pos[0]-(837+i*43),pos[1]-277)<=20 for i in range(4)):
                    theme_index=next(i for i in range(4) if math.hypot(pos[0]-(837+i*43),pos[1]-277)<=20);play_sfx('click')
                elif b['timer30'].collidepoint(pos):set_timer(0)
                elif b['timer60'].collidepoint(pos):set_timer(1)
                elif b['timer90'].collidepoint(pos):set_timer(2)
                elif b['timer120'].collidepoint(pos):set_timer(3)
                elif b['leftmode'].collidepoint(pos):change_mode(MODES[(MODES.index(game_mode)-1)%4])
                elif b['rightmode'].collidepoint(pos):change_mode(MODES[(MODES.index(game_mode)+1)%4])
                else:
                    clicked_mode=next((i for i in range(4) if b[f'mode{i}'].collidepoint(pos)),None)
                    if clicked_mode is not None:change_mode(MODES[clicked_mode])
                    elif CLIP.collidepoint(pos) and playing:
                        idx=hit_arrow(pos)
                        if idx is not None:tap_arrow(idx)
    pygame.quit()

if __name__=='__main__':main()