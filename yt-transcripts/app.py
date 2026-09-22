#!/usr/bin/env python3
"""
Local YouTube transcript + discovery tool — Flask web UI.

Two tabs:
  • Transcripts — paste a mixed batch (video / channel / playlist URLs, or plain
    text searches). Auto-detect each line, expand channels/playlists with yt-dlp
    (--flat-playlist, no downloads), fetch transcripts with youtube-transcript-api
    (manual captions first, auto-generated fallback). One .txt per video plus a
    combined file and a CSV summary.
  • Find Videos — keyword search (yt-dlp ytsearchN, metadata only), filter by
    length / views / upload date, sort, then send chosen videos to the
    Transcripts tab.

Run:  python3 app.py   (see README.md for setup)
"""

import os
import re
import io
import csv
import sys
import time
import threading
import webbrowser
from datetime import datetime

# ---- dependencies (import with a clear message if missing) -------------------
_MISSING = []
try:
    from flask import Flask, request, jsonify, send_file, render_template_string
except Exception:
    _MISSING.append("Flask")
try:
    import yt_dlp
except Exception:
    _MISSING.append("yt-dlp")
try:
    from youtube_transcript_api import YouTubeTranscriptApi
    try:
        from youtube_transcript_api._errors import TranscriptsDisabled, NoTranscriptFound
    except Exception:
        class TranscriptsDisabled(Exception): ...
        class NoTranscriptFound(Exception): ...
except Exception:
    _MISSING.append("youtube-transcript-api")

if _MISSING:
    print("\n[!] Missing packages: " + ", ".join(_MISSING))
    print("    Install them first:")
    print("      python3 -m venv .venv && source .venv/bin/activate")
    print("      pip install -r requirements.txt\n")
    sys.exit(1)

# ---- config ------------------------------------------------------------------
BASE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(BASE, "transcripts")
COMBINED_PATH = os.path.join(OUT_DIR, "youtube_transcripts.txt")
CSV_PATH = os.path.join(OUT_DIR, "youtube_transcripts.csv")
REQUEST_DELAY = 1.2          # seconds between transcript fetches (be gentle)
PORT = int(os.environ.get("PORT", "7654"))

app = Flask(__name__)

# ---- shared job state --------------------------------------------------------
LOCK = threading.Lock()
JOB = {"running": False, "phase": "Idle", "items": [], "done": False,
       "summary": {}, "combined": False, "csv": False, "error": ""}


def reset_job():
    with LOCK:
        JOB.update(running=True, phase="Reading your links…", items=[], done=False,
                   summary={}, combined=False, csv=False, error="")


def snapshot():
    with LOCK:
        return {
            "running": JOB["running"], "phase": JOB["phase"], "done": JOB["done"],
            "summary": dict(JOB["summary"]), "combined": JOB["combined"],
            "csv": JOB["csv"], "error": JOB["error"],
            "items": [dict(i) for i in JOB["items"]],
        }


# ---- link detection ----------------------------------------------------------
def classify(line):
    s = (line or "").strip()
    if not s:
        return "empty"
    low = s.lower()
    is_url = low.startswith("http://") or low.startswith("https://") \
        or "youtube.com" in low or "youtu.be" in low
    if not is_url:
        return "search"
    if "youtu.be/" in low:
        return "video"
    if "/shorts/" in low or "/watch" in low or "watch?v=" in low:
        return "video"
    if "list=" in low or "/playlist" in low:
        return "playlist"
    if "/channel/" in low or "/@" in low or "/c/" in low or "/user/" in low:
        return "channel"
    if "v=" in low and "list=" not in low:
        return "video"
    return "video"


def _video_url(vid):
    return f"https://www.youtube.com/watch?v={vid}"


def _entry_channel(e):
    return (e.get("channel") or e.get("uploader") or "").strip()


def _ytdlp_entries(url, max_n):
    """Return normalized list of {id,title,url,channel} via flat extraction (no download)."""
    opts = {"quiet": True, "no_warnings": True, "extract_flat": True,
            "skip_download": True, "playlistend": max_n, "ignoreerrors": True}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
    out = []

    def add(e):
        if not e or not isinstance(e, dict):
            return
        vid = e.get("id")
        if not vid or len(str(vid)) != 11:
            return
        out.append({"id": vid, "title": (e.get("title") or "").strip(),
                    "url": e.get("webpage_url") or _video_url(vid),
                    "channel": _entry_channel(e)})

    if isinstance(info, dict) and info.get("entries") is not None:
        for e in info["entries"]:
            if isinstance(e, dict) and e.get("entries") is not None:
                for e2 in e["entries"]:
                    add(e2)
            else:
                add(e)
    else:
        add(info)
    return out[:max_n]


def resolve_source(line, kind, max_n):
    if kind == "search":
        return _ytdlp_entries(f"ytsearch1:{line.strip()}", 1)[:1]
    if kind == "video":
        return _ytdlp_entries(line.strip(), 1)[:1]
    target = line.strip()
    if kind == "channel" and not re.search(r"/(videos|streams|shorts)(/|\?|$)", target.lower()):
        target = target.rstrip("/") + "/videos"
    return _ytdlp_entries(target, max_n)[:max_n]


# ---- keyword search (Find Videos tab) ----------------------------------------
def _best_thumb(e):
    if e.get("thumbnail"):
        return e["thumbnail"]
    ths = e.get("thumbnails") or []
    return ths[-1]["url"] if ths and isinstance(ths[-1], dict) and ths[-1].get("url") else ""


def normalize_search_entry(e):
    vid = e.get("id") or ""
    return {
        "id": vid,
        "title": (e.get("title") or "").strip(),
        "url": e.get("webpage_url") or (_video_url(vid) if vid else ""),
        "channel": _entry_channel(e),
        "views": int(e.get("view_count") or 0),
        "duration": int(e.get("duration") or 0),          # seconds
        "upload_date": (e.get("upload_date") or "").strip(),  # YYYYMMDD
        "thumbnail": _best_thumb(e),
    }


def search_videos(query, n):
    """Full metadata search (no downloads) so we get views, length AND upload date."""
    n = max(1, min(int(n), 200))
    opts = {"quiet": True, "no_warnings": True, "skip_download": True,
            "extract_flat": False, "playlistend": n, "ignoreerrors": True,
            "socket_timeout": 20}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(f"ytsearch{n}:{query.strip()}", download=False)
    entries = (info or {}).get("entries") or []
    out = []
    for e in entries:
        if e and e.get("id"):
            out.append(normalize_search_entry(e))
    return out


# ---- transcripts -------------------------------------------------------------
def fetch_transcript(video_id, lang):
    tl = YouTubeTranscriptApi.list_transcripts(video_id)
    for finder, note in ((lambda: tl.find_manually_created_transcript([lang]), "manual"),
                         (lambda: tl.find_generated_transcript([lang]), "auto")):
        try:
            return finder().fetch(), note
        except Exception:
            pass
    transcripts = list(tl)
    if not transcripts:
        raise NoTranscriptFound(video_id, [lang], [])
    transcripts.sort(key=lambda t: 0 if not getattr(t, "is_generated", False) else 1)
    t = transcripts[0]
    try:
        langs = [x["language_code"] for x in (t.translation_languages or [])]
        if getattr(t, "is_translatable", False) and lang in langs:
            return t.translate(lang).fetch(), f"translated→{lang}"
    except Exception:
        pass
    return t.fetch(), f"other lang ({getattr(t, 'language_code', '?')})"


def format_transcript(segments, strip_timestamps):
    lines = []
    for seg in segments:
        text = (seg.get("text") or "").replace("\n", " ").strip()
        if not text:
            continue
        if strip_timestamps:
            lines.append(text)
        else:
            s = int(seg.get("start", 0))
            h, m, sec = s // 3600, (s % 3600) // 60, s % 60
            stamp = f"[{h:02d}:{m:02d}:{sec:02d}]" if h else f"[{m:02d}:{sec:02d}]"
            lines.append(f"{stamp} {text}")
    return "\n".join(lines)


def sanitize(name):
    name = re.sub(r'[\\/:*?"<>|\n\r\t]+', " ", name or "").strip()
    name = re.sub(r"\s+", " ", name)
    return (name[:120].strip() or "untitled")


# ---- worker ------------------------------------------------------------------
def run_job(lines, max_n, lang, strip_timestamps):
    try:
        os.makedirs(OUT_DIR, exist_ok=True)
        sources = [l for l in lines if l.strip()]

        with LOCK:
            JOB["phase"] = "Reading your links…"
        videos, seen = [], set()
        for line in sources:
            kind = classify(line)
            if kind == "empty":
                continue
            try:
                entries = resolve_source(line, kind, max_n)
            except Exception as e:
                with LOCK:
                    JOB["items"].append({"title": line.strip()[:90], "url": "", "id": "",
                                         "channel": "", "kind": kind, "status": "failed",
                                         "words": 0, "note": f"couldn't read: {e}"})
                continue
            if not entries:
                with LOCK:
                    JOB["items"].append({"title": line.strip()[:90], "url": "", "id": "",
                                         "channel": "", "kind": kind, "status": "failed",
                                         "words": 0, "note": "no videos found"})
                continue
            for e in entries:
                if e["id"] in seen:
                    continue
                seen.add(e["id"])
                item = {"title": e["title"] or e["id"], "url": e["url"], "id": e["id"],
                        "channel": e.get("channel", ""), "kind": kind,
                        "status": "pending", "words": 0, "note": kind}
                videos.append(item)
                with LOCK:
                    JOB["items"].append(item)

        with LOCK:
            JOB["phase"] = f"Fetching transcripts… (0/{len(videos)})"
        used_names, found, done_ct = set(), [], 0
        for item in videos:
            item["status"] = "working"
            try:
                segments, note = fetch_transcript(item["id"], lang)
                text = format_transcript(segments, strip_timestamps)
                if not text.strip():
                    item["status"], item["note"] = "skipped", "empty transcript"
                else:
                    fname = sanitize(item["title"])
                    if fname.lower() in used_names:
                        fname = f"{fname} [{item['id']}]"
                    used_names.add(fname.lower())
                    body = f"{item['title']}\n{item['url']}\n\n{text}\n"
                    with open(os.path.join(OUT_DIR, fname + ".txt"), "w", encoding="utf-8") as fh:
                        fh.write(body)
                    item["status"], item["note"] = "found", note
                    item["words"] = len(text.split())
                    found.append(item.copy() | {"text": text})
            except (TranscriptsDisabled, NoTranscriptFound):
                item["status"], item["note"] = "skipped", "no transcript"
            except Exception as e:
                msg = str(e).splitlines()[0][:120] if str(e) else e.__class__.__name__
                item["status"], item["note"] = "failed", msg
            done_ct += 1
            with LOCK:
                JOB["phase"] = f"Fetching transcripts… ({done_ct}/{len(videos)})"
            time.sleep(REQUEST_DELAY)

        n_found = sum(1 for i in videos if i["status"] == "found")
        n_skip = sum(1 for i in videos if i["status"] == "skipped")
        n_fail = sum(1 for i in videos if i["status"] == "failed")
        header = [
            "YouTube transcripts",
            datetime.now().strftime("Generated %Y-%m-%d %H:%M"),
            f"Found: {n_found}   Skipped: {n_skip}   Failed: {n_fail}   "
            f"(from {len(sources)} line{'s' if len(sources) != 1 else ''}, "
            f"{len(videos)} video{'s' if len(videos) != 1 else ''})",
            "=" * 60, "",
        ]
        parts = ["\n".join(header)]
        for f in found:
            parts.append(f"### {f['title']}\n{f['url']}\n\n{f['text']}\n\n{'-'*60}\n")
        with open(COMBINED_PATH, "w", encoding="utf-8") as fh:
            fh.write("\n".join(parts))

        # CSV: one row per video (title, channel, url, status, word_count)
        with open(CSV_PATH, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["title", "channel", "url", "status", "word_count"])
            for it in videos:
                w.writerow([it["title"], it.get("channel", ""), it["url"],
                            it["status"], it.get("words", 0)])

        with LOCK:
            JOB["summary"] = {"found": n_found, "skipped": n_skip, "failed": n_fail,
                              "sources": len(sources), "videos": len(videos)}
            JOB["combined"] = n_found > 0
            JOB["csv"] = len(videos) > 0
            JOB["phase"] = "Done"
            JOB["done"] = True
    except Exception as e:
        with LOCK:
            JOB["error"] = f"{e.__class__.__name__}: {e}"
            JOB["phase"] = "Error"
            JOB["done"] = True
    finally:
        with LOCK:
            JOB["running"] = False


# ---- routes ------------------------------------------------------------------
@app.route("/")
def index():
    return render_template_string(PAGE)


@app.route("/run", methods=["POST"])
def start():
    with LOCK:
        if JOB["running"]:
            return jsonify(ok=False, error="A batch is already running."), 409
    data = request.get_json(force=True, silent=True) or {}
    lines = [l for l in (data.get("text") or "").splitlines()]
    if not any(l.strip() for l in lines):
        return jsonify(ok=False, error="Paste at least one line first."), 400
    try:
        max_n = max(1, min(int(data.get("max", 10)), 500))
    except Exception:
        max_n = 10
    lang = (data.get("lang") or "en").strip() or "en"
    strip_ts = bool(data.get("strip", True))
    reset_job()
    threading.Thread(target=run_job, args=(lines, max_n, lang, strip_ts), daemon=True).start()
    return jsonify(ok=True)


@app.route("/search", methods=["POST"])
def search():
    data = request.get_json(force=True, silent=True) or {}
    query = (data.get("query") or "").strip()
    if not query:
        return jsonify(ok=False, error="Type something to search for."), 400
    try:
        n = max(1, min(int(data.get("n", 30)), 200))
    except Exception:
        n = 30
    try:
        results = search_videos(query, n)
    except Exception as e:
        return jsonify(ok=False, error=f"Search failed: {e}"), 500
    return jsonify(ok=True, results=results)


@app.route("/progress")
def progress():
    return jsonify(snapshot())


@app.route("/download")
def download():
    if not os.path.exists(COMBINED_PATH):
        return "No combined file yet — run a batch first.", 404
    return send_file(COMBINED_PATH, as_attachment=True,
                     download_name=os.path.basename(COMBINED_PATH))


@app.route("/download_csv")
def download_csv():
    if not os.path.exists(CSV_PATH):
        return "No CSV yet — run a batch first.", 404
    return send_file(CSV_PATH, as_attachment=True,
                     download_name=os.path.basename(CSV_PATH))


# ---- page --------------------------------------------------------------------
PAGE = r"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>YouTube Transcripts</title>
<style>
  :root{--bg:#0f1115;--surface:#171a21;--surface2:#1e222b;--border:#2a2f3a;--text:#e8eaf0;
    --muted:#9aa3b2;--accent:#6c8cff;--good:#4bbf87;--skip:#e0a458;--fail:#ff8891;
    --font:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}
  *{box-sizing:border-box} html,body{margin:0}
  body{background:var(--bg);color:var(--text);font-family:var(--font);line-height:1.5}
  .wrap{max-width:960px;margin:0 auto;padding:24px 18px 60px}
  h1{font-size:22px;margin:0 0 14px;letter-spacing:-.3px}
  .tabs{display:flex;gap:6px;margin-bottom:20px;border-bottom:1px solid var(--border)}
  .tabs button{background:none;border:none;color:var(--muted);font-size:15px;font-weight:600;
    padding:10px 14px;cursor:pointer;border-bottom:2px solid transparent;margin-bottom:-1px}
  .tabs button.on{color:var(--text);border-bottom-color:var(--accent)}
  .sub{color:var(--muted);font-size:13px;margin:0 0 16px}
  textarea{width:100%;min-height:150px;background:var(--surface);border:1px solid var(--border);
    color:var(--text);border-radius:12px;padding:13px;font:14px/1.5 ui-monospace,SFMono-Regular,Menlo,monospace;resize:vertical;outline:none}
  textarea:focus,input:focus,select:focus{border-color:var(--accent)}
  .settings{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin:14px 0}
  .fld label{display:block;font-size:12px;color:var(--muted);margin:0 0 5px 2px;font-weight:600}
  input[type=number],input[type=text],select{width:100%;background:var(--surface);border:1px solid var(--border);
    color:var(--text);border-radius:10px;padding:10px 11px;font-size:14px;outline:none}
  .chk{display:flex;align-items:center;gap:9px;background:var(--surface);border:1px solid var(--border);
    border-radius:10px;padding:10px 11px;font-size:14px;cursor:pointer;height:100%}
  .chk input{width:17px;height:17px;accent-color:var(--accent)}
  .row{display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin-top:6px}
  button.act{border:none;border-radius:11px;padding:12px 18px;font-size:15px;font-weight:700;cursor:pointer;
    color:#fff;background:var(--accent);transition:filter .15s,opacity .15s}
  button.act:hover{filter:brightness(1.08)} button.act:disabled{opacity:.5;cursor:default;filter:none}
  button.ghost{background:var(--surface);border:1px solid var(--border);color:var(--text)}
  .phase{margin:18px 0 10px;font-size:13px;color:var(--muted);min-height:18px}
  .list{display:flex;flex-direction:column;gap:7px}
  .item{display:flex;gap:11px;align-items:flex-start;background:var(--surface);border:1px solid var(--border);
    border-radius:10px;padding:10px 12px}
  .item .ic{flex:none;width:20px;text-align:center;font-size:15px;margin-top:1px}
  .item .t{flex:1;min-width:0}
  .item .nm{font-size:14px;word-break:break-word}
  .item .meta{font-size:12px;color:var(--muted);margin-top:2px;word-break:break-all}
  .item.found{border-color:#295c45} .item.skipped{border-color:#5c4a29} .item.failed{border-color:#5c2f34}
  .badge{font-size:11px;font-weight:700;padding:2px 8px;border-radius:999px;flex:none;margin-top:1px}
  .b-found{color:var(--good);background:rgba(75,191,135,.12)}
  .b-skipped{color:var(--skip);background:rgba(224,164,88,.12)}
  .b-failed{color:var(--fail);background:rgba(255,136,145,.12)}
  .b-working,.b-pending{color:var(--muted);background:rgba(154,163,178,.12)}
  .summary{background:var(--surface2);border:1px solid var(--border);border-radius:12px;padding:14px 16px;margin:16px 0;font-size:14px}
  .summary b{color:var(--text)} .err{color:var(--fail)}
  code{background:var(--surface2);padding:1px 6px;border-radius:6px;font-size:12.5px}
  .hint{color:var(--muted);font-size:12px;margin-top:8px}
  /* results table */
  table{width:100%;border-collapse:collapse;margin-top:14px;font-size:13px}
  th,td{text-align:left;padding:9px 8px;border-bottom:1px solid var(--border);vertical-align:top}
  th{color:var(--muted);font-size:12px;font-weight:600;white-space:nowrap}
  td.n{text-align:right;white-space:nowrap;font-variant-numeric:tabular-nums}
  th.n{text-align:right}
  tr:hover td{background:var(--surface)}
  .thumb{width:120px;height:68px;object-fit:cover;border-radius:6px;background:var(--surface2);display:block}
  .vt{font-weight:600}
  .vt a{color:var(--text);text-decoration:none} .vt a:hover{color:var(--accent)}
  .rowsel{display:flex;gap:10px;align-items:center;margin:14px 0 4px;flex-wrap:wrap}
  .cnt{color:var(--muted);font-size:12px}
  .searching{color:var(--muted);font-size:13px;margin-top:14px}
  input[type=checkbox].pick{width:17px;height:17px;accent-color:var(--accent)}
  .hidden{display:none}
</style></head>
<body><div class="wrap">
  <h1>YouTube Transcripts</h1>
  <div class="tabs">
    <button data-tab="tx" class="on">Transcripts</button>
    <button data-tab="find">Find Videos</button>
  </div>

  <!-- ===== TRANSCRIPTS TAB ===== -->
  <section id="tab-tx">
    <p class="sub">Paste any mix of video / channel / playlist URLs or plain-text searches — one per line.</p>
    <textarea id="box" placeholder="https://www.youtube.com/watch?v=...
https://www.youtube.com/@somechannel
https://www.youtube.com/playlist?list=...
best cold plunge review 2026"></textarea>
    <div class="settings">
      <div class="fld"><label>Max videos / channel or playlist</label><input type="number" id="max" value="10" min="1" max="500"></div>
      <div class="fld"><label>Language</label><input type="text" id="lang" value="en"></div>
      <div class="fld"><label>&nbsp;</label><label class="chk"><input type="checkbox" id="strip" checked> Strip timestamps</label></div>
    </div>
    <div class="row">
      <button class="act" id="go">Get Transcripts</button>
      <button class="act ghost" id="dl" disabled>Download combined file</button>
      <button class="act ghost" id="dlcsv" disabled>Download CSV</button>
    </div>
    <div class="hint">Files are also saved to a <code>transcripts/</code> folder next to the app.</div>
    <div class="phase" id="phase"></div>
    <div id="summary"></div>
    <div class="list" id="list"></div>
  </section>

  <!-- ===== FIND VIDEOS TAB ===== -->
  <section id="tab-find" class="hidden">
    <p class="sub">Search YouTube by keyword, filter the results, then send the ones you want to the Transcripts tab.</p>
    <div class="row">
      <input type="text" id="q" placeholder="e.g. sourdough starter guide" style="flex:1;min-width:220px">
      <button class="act" id="search">Search</button>
    </div>
    <div class="settings">
      <div class="fld"><label>Results to fetch</label><input type="number" id="n" value="30" min="1" max="200"></div>
      <div class="fld"><label>Length</label><select id="fLen">
        <option value="any">Any length</option><option value="short">Under 10 min</option>
        <option value="medium">10–30 min</option><option value="long">Over 30 min</option></select></div>
      <div class="fld"><label>Minimum views</label><input type="number" id="fViews" value="0" min="0" step="1000"></div>
      <div class="fld"><label>Upload date</label><select id="fDate">
        <option value="any">Any time</option><option value="month">Past month</option>
        <option value="year">Past year</option></select></div>
      <div class="fld"><label>Sort by</label><select id="fSort">
        <option value="relevance">Relevance</option><option value="views">Views</option>
        <option value="date">Upload date</option></select></div>
    </div>
    <div id="searchNote" class="searching hidden"></div>
    <div id="results"></div>
  </section>
</div>
<script>
const $=s=>document.querySelector(s);
const ICON={found:"✅",skipped:"⤬",failed:"✕",working:"…",pending:"•"};
let timer=null, RESULTS=[];

/* ---- tabs ---- */
function switchTab(t){
  document.querySelectorAll(".tabs button").forEach(b=>b.classList.toggle("on",b.dataset.tab===t));
  $("#tab-tx").classList.toggle("hidden",t!=="tx");
  $("#tab-find").classList.toggle("hidden",t!=="find");
}
document.querySelectorAll(".tabs button").forEach(b=>b.onclick=()=>switchTab(b.dataset.tab));

/* ---- transcripts ---- */
$("#go").onclick=async()=>{
  const text=$("#box").value;
  if(!text.trim()){alert("Paste at least one line first.");return;}
  $("#go").disabled=true;$("#dl").disabled=true;$("#dlcsv").disabled=true;$("#summary").innerHTML="";$("#list").innerHTML="";
  const r=await fetch("/run",{method:"POST",headers:{"Content-Type":"application/json"},
    body:JSON.stringify({text,max:+$("#max").value||10,lang:$("#lang").value||"en",strip:$("#strip").checked})});
  const j=await r.json();
  if(!j.ok){alert(j.error||"Failed to start");$("#go").disabled=false;return;}
  poll();timer=setInterval(poll,1000);
};
$("#dl").onclick=()=>{location.href="/download";};
$("#dlcsv").onclick=()=>{location.href="/download_csv";};
async function poll(){
  const s=await (await fetch("/progress")).json();
  $("#phase").textContent=s.phase;
  $("#list").innerHTML=s.items.map(it=>`
    <div class="item ${it.status}">
      <span class="ic">${ICON[it.status]||"•"}</span>
      <span class="t"><div class="nm">${esc(it.title)}</div>
        <div class="meta">${esc(it.url||it.note||"")}${it.url&&it.note?" · "+esc(it.note):""}</div></span>
      <span class="badge b-${it.status}">${it.status}</span>
    </div>`).join("");
  if(s.done){
    clearInterval(timer);$("#go").disabled=false;
    if(s.error){$("#summary").innerHTML=`<div class="summary err">Error: ${esc(s.error)}</div>`;}
    else{const m=s.summary;
      $("#summary").innerHTML=`<div class="summary"><b>${m.found}</b> found · <b>${m.skipped}</b> skipped · <b>${m.failed}</b> failed
        <span style="color:var(--muted)">(${m.videos} videos from ${m.sources} lines)</span></div>`;
      $("#dl").disabled=!s.combined;$("#dlcsv").disabled=!s.csv;}
  }
}

/* ---- find videos ---- */
$("#search").onclick=doSearch;
$("#q").addEventListener("keydown",e=>{if(e.key==="Enter")doSearch();});
["#fLen","#fViews","#fDate","#fSort"].forEach(s=>$(s).addEventListener("input",renderResults));
async function doSearch(){
  const query=$("#q").value.trim();
  if(!query){alert("Type something to search for.");return;}
  $("#search").disabled=true;$("#results").innerHTML="";
  const note=$("#searchNote");note.classList.remove("hidden");note.textContent="Searching YouTube… (fetching metadata, no downloads)";
  try{
    const r=await fetch("/search",{method:"POST",headers:{"Content-Type":"application/json"},
      body:JSON.stringify({query,n:+$("#n").value||30})});
    const j=await r.json();
    if(!j.ok){note.textContent="";note.classList.add("hidden");alert(j.error||"Search failed");return;}
    RESULTS=j.results||[];note.classList.add("hidden");
    renderResults();
  }catch(e){note.textContent="";note.classList.add("hidden");alert("Search failed: "+e);}
  finally{$("#search").disabled=false;}
}
/* pure, testable filter+sort */
function applyFilters(results, o){
  const now=o.now?new Date(o.now):new Date();
  const days=ymd=>{ if(!/^\d{8}$/.test(ymd))return null;
    const d=new Date(+ymd.slice(0,4),+ymd.slice(4,6)-1,+ymd.slice(6,8)); return (now-d)/86400000; };
  let r=results.filter(v=>{
    const dur=v.duration||0;
    if(o.length==="short" && !(dur>0&&dur<600))return false;
    if(o.length==="medium" && !(dur>=600&&dur<=1800))return false;
    if(o.length==="long" && !(dur>1800))return false;
    if(o.minViews && (v.views||0)<o.minViews)return false;
    if(o.date&&o.date!=="any"){ const ds=days(v.upload_date); if(ds===null)return false;
      if(o.date==="month"&&ds>31)return false; if(o.date==="year"&&ds>366)return false; }
    return true;
  });
  if(o.sort==="views")r=r.slice().sort((a,b)=>(b.views||0)-(a.views||0));
  else if(o.sort==="date")r=r.slice().sort((a,b)=>(b.upload_date||"").localeCompare(a.upload_date||""));
  return r;
}
window.__applyFilters=applyFilters;
window.__setResults=(mock)=>{RESULTS=mock;renderResults();};
function currentOpts(){return {length:$("#fLen").value,minViews:+$("#fViews").value||0,date:$("#fDate").value,sort:$("#fSort").value};}
function renderResults(){
  const filtered=applyFilters(RESULTS,currentOpts());
  if(!RESULTS.length){$("#results").innerHTML=`<p class="hint">No results yet — run a search.</p>`;return;}
  $("#results").innerHTML=`
    <div class="rowsel">
      <button class="act ghost" id="selAll">Select all</button>
      <button class="act ghost" id="selNone">Select none</button>
      <button class="act" id="send">Send to Transcripts</button>
      <span class="cnt" id="rcount"></span>
    </div>
    <table><thead><tr>
      <th></th><th></th><th>Title</th><th>Channel</th><th class="n">Views</th><th class="n">Length</th><th>Uploaded</th>
    </tr></thead><tbody>
    ${filtered.map(v=>`<tr>
      <td><input type="checkbox" class="pick" data-url="${esc(v.url)}"></td>
      <td>${v.thumbnail?`<img class="thumb" loading="lazy" src="${esc(v.thumbnail)}" alt="">`:`<div class="thumb"></div>`}</td>
      <td class="vt"><a href="${esc(v.url)}" target="_blank" rel="noopener">${esc(v.title)}</a></td>
      <td>${esc(v.channel||"—")}</td>
      <td class="n">${fmtViews(v.views)}</td>
      <td class="n">${fmtDur(v.duration)}</td>
      <td>${fmtDate(v.upload_date)}</td>
    </tr>`).join("")}
    </tbody></table>`;
  const upd=()=>{const c=document.querySelectorAll(".pick:checked").length;
    $("#rcount").textContent=`${filtered.length} shown · ${c} selected`;};
  document.querySelectorAll(".pick").forEach(cb=>cb.onchange=upd);
  $("#selAll").onclick=()=>{document.querySelectorAll(".pick").forEach(cb=>cb.checked=true);upd();};
  $("#selNone").onclick=()=>{document.querySelectorAll(".pick").forEach(cb=>cb.checked=false);upd();};
  $("#send").onclick=()=>{
    const urls=[...document.querySelectorAll(".pick:checked")].map(cb=>cb.dataset.url);
    if(!urls.length){alert("Tick at least one video first.");return;}
    const box=$("#box");const cur=box.value.trim();
    box.value=(cur?cur+"\n":"")+urls.join("\n");
    switchTab("tx");box.scrollIntoView({behavior:"smooth"});
  };
  upd();
}
function fmtViews(n){n=+n||0;if(n>=1e6)return (n/1e6).toFixed(n>=1e7?0:1)+"M";if(n>=1e3)return (n/1e3).toFixed(n>=1e4?0:1)+"K";return ""+n;}
function fmtDur(s){s=+s||0;if(!s)return "—";const h=Math.floor(s/3600),m=Math.floor(s%3600/60),ss=s%60;
  return h?`${h}:${String(m).padStart(2,"0")}:${String(ss).padStart(2,"0")}`:`${m}:${String(ss).padStart(2,"0")}`;}
function fmtDate(ymd){if(!/^\d{8}$/.test(ymd||""))return "—";return ymd.slice(0,4)+"-"+ymd.slice(4,6)+"-"+ymd.slice(6,8);}
function esc(s){return String(s==null?"":s).replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));}
</script>
</body></html>"""


def main():
    url = f"http://127.0.0.1:{PORT}/"
    print("\n  YouTube Transcript tool")
    print(f"  Open:  {url}")
    print("  Stop:  Ctrl+C\n")
    try:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    except Exception:
        pass
    app.run(host="127.0.0.1", port=PORT, threaded=True)


if __name__ == "__main__":
    main()
