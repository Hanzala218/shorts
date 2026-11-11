"""
Viral Shorts Maker - SINGLE FILE (backend + frontend)

Install:
    1) FFmpeg install karein (ffmpeg -version chalna chahiye)
    2) pip install flask flask-limiter yt-dlp faster-whisper gunicorn
Run (local):
    python viral_shorts.py      ->  browser: http://127.0.0.1:5000
Run (live):
    gunicorn -w 1 --threads 16 -t 300 -b 0.0.0.0:5000 viral_shorts:app
Optional env: ACCESS_CODE, ALLOWED_DOMAINS, MAX_DURATION_MIN, MAX_UPLOAD_MB, MAX_WORKERS,
              WHISPER_MODEL (small/medium), COOKIES_FILE, CORS_ORIGIN, DATA_DIR, PORT
"""
import os, re, json, time, glob, hmac, shutil, sqlite3, secrets, logging, threading, subprocess
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse
from flask import Flask, request, jsonify, send_from_directory, Response
from werkzeug.middleware.proxy_fix import ProxyFix
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import yt_dlp
from faster_whisper import WhisperModel

# ====================================================================== FRONTEND
INDEX_HTML = r'''<!DOCTYPE html>
<html lang="hi">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ClipKaro – Long video se viral Shorts</title>
<style>
  :root{
    --bg:#F3F5F9; --ink:#14213D; --muted:#5B6678; --card:#FFFFFF; --line:#D9DEE8;
    --accent:#FF4D6D; --accent-ink:#FFFFFF; --ok:#1B9E77;
  }
  @media (prefers-color-scheme: dark){
    :root{ --bg:#0F1626; --ink:#EEF1F7; --muted:#9AA6BC; --card:#18213A; --line:#2A3556; }
  }
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.55 "Trebuchet MS",system-ui,sans-serif}
  main{max-width:960px;margin:0 auto;padding:48px 20px 80px}
  h1{font-size:clamp(2rem,5vw,3.2rem);line-height:1.1;margin:0 0 12px;letter-spacing:-.02em}
  p.lead{color:var(--muted);max-width:60ch;margin:0 0 32px}
  .box{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:20px}
  .row{display:flex;gap:10px;flex-wrap:wrap}
  input[type=url],input[type=password],input[type=file]{flex:1 1 320px;padding:14px 16px;border-radius:10px;border:1px solid var(--line);
    background:transparent;color:var(--ink);font-size:1rem}
  input[type=url]:focus,select:focus,button:focus-visible{outline:3px solid var(--accent);outline-offset:2px}
  select{padding:14px;border-radius:10px;border:1px solid var(--line);background:transparent;color:var(--ink)}
  button.go{padding:14px 26px;border:0;border-radius:10px;background:var(--accent);color:var(--accent-ink);
    font-weight:700;font-size:1rem;cursor:pointer}
  button.go:disabled{opacity:.55;cursor:wait}
  #status{margin-top:20px;display:none}
  .bar{height:10px;background:var(--line);border-radius:99px;overflow:hidden;margin-top:8px}
  .bar>i{display:block;height:100%;width:0;background:var(--accent);transition:width .4s}
  #err{color:#d6335a;margin-top:12px}
  #results{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:18px;margin-top:32px}
  .clip{background:var(--card);border:1px solid var(--line);border-radius:14px;overflow:hidden}
  .clip video{width:100%;aspect-ratio:9/16;background:#000;display:block}
  .clip .meta{padding:12px}
  .clip .t{font-weight:700;font-size:.95rem;margin:0 0 4px}
  .clip small{color:var(--muted)}
  .clip a.dl{display:block;margin-top:10px;text-align:center;padding:10px;border-radius:8px;
    background:var(--ink);color:var(--bg);text-decoration:none;font-weight:700}
  .note{color:var(--muted);font-size:.85rem;margin-top:28px}
</style>
</head>
<body>
<main>
  <h1>Lambi video daalo, viral Shorts pao.</h1>
  <p class="lead">Video ka link paste karein. Hum best moments dhoondh kar 9:16 Shorts banate hain, captions ke sath, aur aap unhe seedha download kar sakte hain.</p>

  <div class="box">
    <div class="row">
      <input id="url" type="url" placeholder="https://www.youtube.com/watch?v=..." aria-label="Video link">
      <select id="count" aria-label="Kitne shorts">
        <option value="3">3 shorts</option>
        <option value="5" selected>5 shorts</option>
        <option value="8">8 shorts</option>
      </select>
      <select id="len" aria-label="Short ki length">
        <option value="15,30">15–30 sec</option>
        <option value="20,55" selected>20–55 sec</option>
        <option value="45,85">45–85 sec</option>
      </select>
      <button class="go" id="go">Shorts banao</button>
    </div>
    <div class="row" style="margin-top:12px">
      <input id="file" type="file" accept="video/*" aria-label="Ya apni video file upload karein">
      <input id="code" type="password" placeholder="Access code (agar mila ho)" aria-label="Access code">
    </div>
    <label style="display:block;margin-top:12px;color:var(--muted)">
      <input type="checkbox" id="ok"> Main confirm karta hu ki is video par mera haq ya permission hai.
    </label>
    <div id="status" aria-live="polite">
      <div id="msg"></div>
      <div class="bar"><i id="fill"></i></div>
    </div>
    <div id="err" role="alert"></div>
  </div>

  <div id="results"></div>
  <p class="note">Sirf wahi videos use karein jinke aap owner hain ya jinki aapke paas permission hai.</p>
</main>

<script>
  // Backend ka address. Same server se serve ho raha ho to khaali chhod dein.
  const API = "";
  const $ = id => document.getElementById(id);
  let timer = null;

  $("go").addEventListener("click", async () => {
    const url = $("url").value.trim(), file = $("file").files[0];
    $("err").textContent = ""; $("results").innerHTML = "";
    if (!file && !/^https:\/\//.test(url)) { $("err").textContent = "Https link daalein ya video file chunein."; return; }
    if (!$("ok").checked) { $("err").textContent = "Pehle permission wala box tick karein."; return; }

    const [min_len, max_len] = $("len").value.split(",").map(Number);
    const headers = { "X-Access-Code": $("code").value };
    $("go").disabled = true; $("status").style.display = "block";
    setProgress(2, file ? "File upload ho rahi hai..." : "Shuru ho raha hai...");
    try {
      let r;
      if (file) {
        const fd = new FormData();
        fd.append("file", file); fd.append("accepted", "true"); fd.append("clips", $("count").value);
        fd.append("min_len", min_len); fd.append("max_len", max_len);
        r = await fetch(`${API}/api/upload`, { method: "POST", headers, body: fd });
      } else {
        r = await fetch(`${API}/api/jobs`, {
          method: "POST", headers: { ...headers, "Content-Type": "application/json" },
          body: JSON.stringify({ url, accepted: true, clips: +$("count").value, min_len, max_len })
        });
      }
      const data = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(data.error || "Server error");
      poll(data.job_id);
    } catch (e) { fail(e.message); }
  });

  function poll(id) {
    clearInterval(timer);
    timer = setInterval(async () => {
      try {
        const job = await (await fetch(`${API}/api/jobs/${id}`)).json();
        setProgress(job.progress || 0, job.message || "");
        if (job.status === "done") { clearInterval(timer); show(job.clips); $("go").disabled = false; }
        if (job.status === "error") { clearInterval(timer); fail(job.message); }
      } catch (e) { clearInterval(timer); fail("Server se connection toot gaya."); }
    }, 2500);
  }

  function setProgress(p, m) { $("fill").style.width = p + "%"; $("msg").textContent = m; }
  function fail(m) { $("err").textContent = "Error: " + m; $("go").disabled = false; $("status").style.display = "none"; }

  function show(clips) {
    $("status").style.display = "none";
    $("results").innerHTML = clips.map(c => `
      <article class="clip">
        <video src="${API}${c.url}" controls playsinline preload="metadata"></video>
        <div class="meta">
          <p class="t">${esc(c.title)}...</p>
          <small>${c.start}s – ${c.end}s · viral score ${c.score}</small>
          <a class="dl" href="${API}${c.url}?download=1" download>Download</a>
        </div>
      </article>`).join("");
  }
  const esc = s => s.replace(/[&<>"]/g, ch => ({ "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;" }[ch]));
</script>
</body>
</html>
'''

# ================================================================ PIPELINE (AI + FFmpeg)
_model = None


def get_model():
    global _model
    if _model is None:
        _model = WhisperModel(os.environ.get("WHISPER_MODEL", "small"),
                              device=os.environ.get("WHISPER_DEVICE", "cpu"),
                              compute_type=os.environ.get("WHISPER_COMPUTE", "int8"))
    return _model


def probe_duration(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "default=nw=1:nk=1", path],
                         capture_output=True, text=True, timeout=60, check=True).stdout.strip()
    return float(out)


# -------------------------------------------------------------- transcribe
def transcribe(path):
    segments, info = get_model().transcribe(path, word_timestamps=True, vad_filter=True)
    segs = []
    for s in segments:
        words = [{"w": w.word.strip(), "s": w.start, "e": w.end} for w in (s.words or []) if w.word.strip()]
        if words:
            segs.append({"start": s.start, "end": s.end, "text": s.text.strip(), "words": words})
    return segs


# ------------------------------------------------------- viral moment picker
HOOKS = re.compile(
    r"\b(secret|never|always|mistake|truth|nobody|everyone|money|free|best|worst|"
    r"warning|shocking|crazy|biggest|why|how|"
    r"raaz|sach|paisa|galti|sabse|kabhi|zaroor|dhyan)\b", re.I)


def score_text(text, duration):
    words = len(text.split())
    score = 0.0
    score += len(HOOKS.findall(text)) * 2.0           # hook words
    score += text.count("?") * 1.5                     # questions keep viewers
    score += text.count("!") * 1.0
    score += len(re.findall(r"\d+", text)) * 0.8       # numbers / stats
    score += min(words / max(duration, 1), 3.5)        # speech density
    return score


def pick_clips(segs, n=5, min_len=20, max_len=55):
    """Slide a window over transcript segments, score it, keep best non-overlapping."""
    cands = []
    for i in range(len(segs)):
        start = segs[i]["start"]
        j = i
        while j < len(segs) and segs[j]["end"] - start <= max_len:
            j += 1
        # window ends at the last segment that still fits
        for k in range(i, j):
            dur = segs[k]["end"] - start
            if dur >= min_len:
                text = " ".join(s["text"] for s in segs[i:k + 1])
                # bonus: opening line is a hook
                bonus = 2.0 if segs[i]["text"].strip().endswith("?") or HOOKS.search(segs[i]["text"]) else 0
                cands.append({"i": i, "k": k, "start": start, "end": segs[k]["end"],
                              "score": score_text(text, dur) + bonus})
    cands.sort(key=lambda c: c["score"], reverse=True)
    chosen = []
    for c in cands:
        if all(c["end"] <= x["start"] or c["start"] >= x["end"] for x in chosen):
            chosen.append(c)
        if len(chosen) >= n:
            break
    chosen.sort(key=lambda c: c["start"])
    return chosen


# ---------------------------------------------------------------- captions
def ass_time(t):
    t = max(t, 0)
    h, m, s = int(t // 3600), int(t % 3600 // 60), t % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def build_ass(words, clip_start, path, group=3):
    """Word-by-word highlighted captions (TikTok style). Active word = yellow."""
    header = (
        "[Script Info]\nScriptType: v4.00+\nPlayResX: 1080\nPlayResY: 1920\n\n"
        "[V4+ Styles]\n"
        "Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,"
        "Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,"
        "Alignment,MarginL,MarginR,MarginV,Encoding\n"
        "Style: Cap,Arial,84,&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,"
        "-1,0,0,0,100,100,0,0,1,6,2,2,60,60,520,1\n\n"
        "[Events]\nFormat: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text\n"
    )
    lines = []
    for g in range(0, len(words), group):
        chunk = words[g:g + group]
        for idx, w in enumerate(chunk):
            start = w["s"] - clip_start
            end = (chunk[idx + 1]["s"] if idx + 1 < len(chunk) else w["e"]) - clip_start
            parts = []
            for j, x in enumerate(chunk):
                txt = x["w"].upper().replace("{", "").replace("}", "")
                parts.append(("{\\c&H00D2FF&}" + txt + "{\\c&HFFFFFF&}") if j == idx else txt)
            lines.append(f"Dialogue: 0,{ass_time(start)},{ass_time(end)},Cap,,0,0,0,,{' '.join(parts)}")
    with open(path, "w", encoding="utf-8") as f:
        f.write(header + "\n".join(lines))


def render_clip(job_dir, src, clip, segs, n):
    words = [w for s in segs[clip["i"]:clip["k"] + 1] for w in s["words"]]
    ass_name = f"clip{n}.ass"
    build_ass(words, clip["start"], os.path.join(job_dir, ass_name))
    out = f"clip{n}.mp4"
    dur = clip["end"] - clip["start"]
    cmd = [
        "ffmpeg", "-y", "-ss", f"{clip['start']:.2f}", "-t", f"{dur:.2f}", "-i", src,
        "-vf", f"crop='min(iw,ih*9/16)':ih,scale=1080:1920,subtitles={ass_name}",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "22",
        "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", out,
    ]
    subprocess.run(cmd, cwd=job_dir, check=True, capture_output=True, timeout=900)
    return out

# ===================================================================== SERVER

E = os.environ.get
BASE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = E("DATA_DIR", os.path.join(BASE, "data"))
JOBS_DIR = os.path.join(DATA_DIR, "jobs")
DB_PATH = os.path.join(DATA_DIR, "jobs.db")
os.makedirs(JOBS_DIR, exist_ok=True)

ALLOWED_DOMAINS = [d.strip().lower() for d in E("ALLOWED_DOMAINS", "youtube.com,youtu.be,vimeo.com").split(",") if d.strip()]
MAX_DURATION_MIN = int(E("MAX_DURATION_MIN", "60"))
MAX_UPLOAD_MB = int(E("MAX_UPLOAD_MB", "500"))
MAX_WORKERS = int(E("MAX_WORKERS", "1"))            # parallel video jobs (CPU heavy!)
MAX_ACTIVE_PER_IP = int(E("MAX_ACTIVE_PER_IP", "2"))
RETENTION_HOURS = int(E("RETENTION_HOURS", "24"))
ACCESS_CODE = E("ACCESS_CODE", "")                  # empty = public site
COOKIES_FILE = E("COOKIES_FILE", "")                # optional yt-dlp cookies.txt
UPLOAD_EXT = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"}

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("shorts")

app = Flask(__name__, static_folder=None)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)  # behind Caddy
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_MB * 1024 * 1024 + 1024 * 1024
limiter = Limiter(get_remote_address, app=app, default_limits=["600/hour"], storage_uri="memory://")
pool = ThreadPoolExecutor(max_workers=MAX_WORKERS)


class UserError(Exception):
    """Message is safe to show to the user."""


# ------------------------------------------------------------------ database
def q(sql, args=(), one=False):
    c = sqlite3.connect(DB_PATH, timeout=30)
    c.row_factory = sqlite3.Row
    try:
        cur = c.execute(sql, args)
        c.commit()
        rows = cur.fetchall()
        return (rows[0] if rows else None) if one else rows
    finally:
        c.close()


def init_db():
    q("""CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, ip TEXT, status TEXT,
         progress INTEGER, message TEXT, clips TEXT, created REAL)""")
    q("UPDATE jobs SET status='error', message='Server restart hua, dobara try karein.' "
      "WHERE status NOT IN ('done','error')")


def update(job_id, **kw):
    if "clips" in kw:
        kw["clips"] = json.dumps(kw["clips"])
    sets = ", ".join(f"{k}=?" for k in kw)
    q(f"UPDATE jobs SET {sets} WHERE id=?", (*kw.values(), job_id))


# ---------------------------------------------------------------- validation
def allowed_url(url):
    p = urlparse(url)
    if p.scheme != "https" or not p.hostname:
        return False
    h = p.hostname.lower()
    return any(h == d or h.endswith("." + d) for d in ALLOWED_DOMAINS)


def check_access():
    if ACCESS_CODE and not hmac.compare_digest(request.headers.get("X-Access-Code", ""), ACCESS_CODE):
        return jsonify(error="Access code galat hai."), 401
    return None


def int_arg(src, key, default, lo, hi):
    try:
        return max(lo, min(int(src.get(key, default)), hi))
    except (TypeError, ValueError):
        return default


def new_job(kind_ok_dir=True):
    ip = get_remote_address()
    active = q("SELECT COUNT(*) AS n FROM jobs WHERE ip=? AND status NOT IN ('done','error')", (ip,), one=True)["n"]
    if active >= MAX_ACTIVE_PER_IP:
        return None, None, (jsonify(error="Aapke pehle se jobs chal rahe hain. Unke khatam hone ka intezaar karein."), 429)
    job_id = secrets.token_hex(12)
    q("INSERT INTO jobs VALUES(?,?,?,?,?,?,?)", (job_id, ip, "queued", 0, "Queue mein hai...", "[]", time.time()))
    d = os.path.join(JOBS_DIR, job_id)
    os.makedirs(d, exist_ok=True)
    return job_id, d, None


# ------------------------------------------------------------------ pipeline
def download(url, job_dir):
    opts = {
        "format": "bv*[height<=1080]+ba/b[height<=1080]/b",
        "merge_output_format": "mp4",
        "outtmpl": os.path.join(job_dir, "source.%(ext)s"),
        "noplaylist": True, "quiet": True, "socket_timeout": 30, "retries": 3,
        "max_filesize": 2 * 1024 ** 3,
    }
    if COOKIES_FILE and os.path.exists(COOKIES_FILE):
        opts["cookiefile"] = COOKIES_FILE
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if info.get("is_live"):
                raise UserError("Live stream support nahi hai.")
            if (info.get("duration") or 0) > MAX_DURATION_MIN * 60:
                raise UserError(f"Video {MAX_DURATION_MIN} minute se chhoti honi chahiye.")
            ydl.download([url])
    except yt_dlp.utils.DownloadError as e:
        log.warning("download failed: %s", e)
        raise UserError("Video download nahi ho paya (private, blocked ya galat link).")
    return find_source(job_dir)


def find_source(job_dir):
    files = [f for f in glob.glob(os.path.join(job_dir, "source.*")) if not f.endswith((".part", ".ytdl"))]
    if not files:
        raise UserError("Video file nahi mili.")
    return files[0]


def run_job(job_id, kind, url, n, min_len, max_len):
    job_dir = os.path.join(JOBS_DIR, job_id)
    try:
        if kind == "url":
            update(job_id, status="downloading", progress=10, message="Video download ho raha hai...")
            src = download(url, job_dir)
        else:
            src = find_source(job_dir)
        if probe_duration(src) > MAX_DURATION_MIN * 60:
            raise UserError(f"Video {MAX_DURATION_MIN} minute se chhoti honi chahiye.")

        update(job_id, status="transcribing", progress=35, message="Speech ko text mein badal rahe hain...")
        segs = transcribe(src)
        if not segs:
            raise UserError("Video mein koi speech nahi mili.")

        update(job_id, status="analyzing", progress=55, message="Best viral moments dhoondh rahe hain...")
        picks = pick_clips(segs, n, min_len, max_len)
        if not picks:
            raise UserError("Is video mein se koi short nahi ban paya. Chhoti length try karein.")

        clips = []
        for i, c in enumerate(picks, 1):
            update(job_id, status="rendering", progress=60 + int(35 * i / len(picks)),
                   message=f"Short {i}/{len(picks)} ban raha hai (captions ke sath)...")
            fname = render_clip(job_dir, src, c, segs, i)
            clips.append({"file": fname, "start": round(c["start"], 1), "end": round(c["end"], 1),
                          "score": round(c["score"], 1),
                          "title": " ".join(segs[c["i"]]["text"].split()[:10]),
                          "url": f"/api/clips/{job_id}/{fname}"})
        for f in glob.glob(os.path.join(job_dir, "source.*")) + glob.glob(os.path.join(job_dir, "*.ass")):
            os.remove(f)  # save disk
        update(job_id, status="done", progress=100, message="Ho gaya!", clips=clips)
    except UserError as e:
        update(job_id, status="error", message=str(e))
    except Exception:
        log.exception("job %s failed", job_id)
        update(job_id, status="error", message="Processing fail ho gaya. Thodi der baad dobara try karein.")


# -------------------------------------------------------------------- routes
@app.post("/api/jobs")
@limiter.limit("10/hour;3/minute")
def create_job():
    if (resp := check_access()):
        return resp
    data = request.get_json(silent=True) or {}
    url = (data.get("url") or "").strip()
    if not data.get("accepted"):
        return jsonify(error="Pehle confirm karein ki video par aapka haq/permission hai."), 400
    if not allowed_url(url):
        return jsonify(error="Sirf is sites ke https links allowed hain: " + ", ".join(ALLOWED_DOMAINS)), 400
    job_id, _, err = new_job()
    if err:
        return err
    n = int_arg(data, "clips", 5, 1, 8)
    pool.submit(run_job, job_id, "url", url, n, int_arg(data, "min_len", 20, 10, 60), int_arg(data, "max_len", 55, 15, 90))
    return jsonify(job_id=job_id)


@app.post("/api/upload")
@limiter.limit("10/hour;3/minute")
def upload():
    if (resp := check_access()):
        return resp
    f = request.files.get("file")
    if request.form.get("accepted") != "true":
        return jsonify(error="Pehle confirm karein ki video par aapka haq/permission hai."), 400
    ext = os.path.splitext(f.filename or "")[1].lower() if f else ""
    if ext not in UPLOAD_EXT:
        return jsonify(error="Supported formats: " + ", ".join(sorted(UPLOAD_EXT))), 400
    job_id, job_dir, err = new_job()
    if err:
        return err
    f.save(os.path.join(job_dir, "source" + ext))
    n = int_arg(request.form, "clips", 5, 1, 8)
    pool.submit(run_job, job_id, "upload", None, n, int_arg(request.form, "min_len", 20, 10, 60), int_arg(request.form, "max_len", 55, 15, 90))
    return jsonify(job_id=job_id)


@app.get("/api/jobs/<job_id>")
def job_status(job_id):
    if not re.fullmatch(r"[0-9a-f]{24}", job_id):
        return jsonify(error="Job nahi mila"), 404
    r = q("SELECT status, progress, message, clips FROM jobs WHERE id=?", (job_id,), one=True)
    if not r:
        return jsonify(error="Job nahi mila (ya delete ho chuka hai)"), 404
    return jsonify(status=r["status"], progress=r["progress"], message=r["message"], clips=json.loads(r["clips"]))


@app.get("/api/clips/<job_id>/<name>")
def get_clip(job_id, name):
    if not re.fullmatch(r"clip\d+\.mp4", name) or not re.fullmatch(r"[0-9a-f]{24}", job_id):
        return "Not found", 404
    dl = request.args.get("download") == "1"
    return send_from_directory(os.path.join(JOBS_DIR, job_id), name, as_attachment=dl, download_name=f"short_{name}")


@app.get("/api/health")
def health():
    return jsonify(ok=True)


@app.get("/")
def index():
    return Response(INDEX_HTML, mimetype="text/html")


CORS_ORIGIN = E("CORS_ORIGIN", "")  # e.g. https://mysite.com ; leave empty if Flask serves the page


@app.after_request
def cors(resp):
    if CORS_ORIGIN:
        resp.headers["Access-Control-Allow-Origin"] = CORS_ORIGIN
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type, X-Access-Code"
        resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return resp


@app.errorhandler(429)
def too_many(_):
    return jsonify(error="Bahut zyada requests. Thodi der baad try karein."), 429


@app.errorhandler(413)
def too_big(_):
    return jsonify(error=f"File {MAX_UPLOAD_MB} MB se badi hai."), 413


# ------------------------------------------------------------------- cleanup
def cleanup_loop():
    while True:
        try:
            cutoff = time.time() - RETENTION_HOURS * 3600
            for r in q("SELECT id FROM jobs WHERE created < ? AND status IN ('done','error')", (cutoff,)):
                shutil.rmtree(os.path.join(JOBS_DIR, r["id"]), ignore_errors=True)
                q("DELETE FROM jobs WHERE id=?", (r["id"],))
        except Exception:
            log.exception("cleanup failed")
        time.sleep(1800)


for tool in ("ffmpeg", "ffprobe"):
    if not shutil.which(tool):
        raise SystemExit(f"ERROR: {tool} install nahi hai. Pehle FFmpeg install karein aur PATH mein jodein.")

init_db()
threading.Thread(target=cleanup_loop, daemon=True).start()

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(E("PORT", "5000")))
