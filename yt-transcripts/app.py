#!/usr/bin/env python3
"""
Local YouTube transcript tool — Flask web UI.

Paste a mixed batch of lines (video URLs, channel URLs, playlist URLs, or plain
text searches). The tool auto-detects each line, expands channels/playlists with
yt-dlp (--flat-playlist, no downloads), fetches transcripts with
youtube-transcript-api (manual captions first, auto-generated as fallback), skips
videos with no transcript, and writes one .txt per video plus one combined file.

Run:  python3 app.py   (see README.md for setup)
"""

import os
import re
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
    except Exception:  # older/newer layouts
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
COMBINED_PATH = os.path.join(OUT_DIR, "_ALL_transcripts.txt")
REQUEST_DELAY = 1.2          # seconds between transcript fetches (be gentle)
PORT = int(os.environ.get("PORT", "7654"))

app = Flask(__name__)

# ---- shared job state --------------------------------------------------------
LOCK = threading.Lock()
JOB = {"running": False, "phase": "Idle", "items": [], "done": False,
       "summary": {}, "combined": False, "error": ""}


def reset_job():
    with LOCK:
        JOB.update(running=True, phase="Reading your links…", items=[], done=False,
                   summary={}, combined=False, error="")


def snapshot():
    with LOCK:
        return {
            "running": JOB["running"], "phase": JOB["phase"], "done": JOB["done"],
            "summary": dict(JOB["summary"]), "combined": JOB["combined"],
            "error": JOB["error"],
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


def _ytdlp_entries(url, max_n):
    """Return a normalized list of {id,title,url} using flat extraction (no download)."""
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
                    "url": e.get("webpage_url") or _video_url(vid)})

    if isinstance(info, dict) and info.get("entries") is not None:
        for e in info["entries"]:
            if isinstance(e, dict) and e.get("entries") is not None:  # nested (channel tabs)
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
    # channel / playlist
    target = line.strip()
    if kind == "channel" and not re.search(r"/(videos|streams|shorts)(/|\?|$)", target.lower()):
        target = target.rstrip("/") + "/videos"
    return _ytdlp_entries(target, max_n)[:max_n]


# ---- transcripts -------------------------------------------------------------
def fetch_transcript(video_id, lang):
    """Return (segments, note). Manual captions preferred, then auto, then translate."""
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
    return t.fetch(), f"other lang ({getattr(t,'language_code','?')})"


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

        # 1) resolve every line into concrete videos
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
                item = {"title": line.strip()[:90], "url": "", "id": "",
                        "kind": kind, "status": "failed", "note": f"couldn't read: {e}"}
                with LOCK:
                    JOB["items"].append(item)
                continue
            if not entries:
                with LOCK:
                    JOB["items"].append({"title": line.strip()[:90], "url": "", "id": "",
                                         "kind": kind, "status": "failed",
                                         "note": "no videos found"})
                continue
            for e in entries:
                if e["id"] in seen:
                    continue
                seen.add(e["id"])
                item = {"title": e["title"] or e["id"], "url": e["url"], "id": e["id"],
                        "kind": kind, "status": "pending", "note": kind}
                videos.append(item)
                with LOCK:
                    JOB["items"].append(item)

        # 2) fetch transcripts
        with LOCK:
            JOB["phase"] = f"Fetching transcripts… (0/{len(videos)})"
        used_names, found = set(), []
        done_ct = 0
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

        # 3) combined file + summary
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

        with LOCK:
            JOB["summary"] = {"found": n_found, "skipped": n_skip, "failed": n_fail,
                              "sources": len(sources), "videos": len(videos)}
            JOB["combined"] = n_found > 0
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
    threading.Thread(target=run_job, args=(lines, max_n, lang, strip_ts),
                     daemon=True).start()
    return jsonify(ok=True)


@app.route("/progress")
def progress():
    return jsonify(snapshot())


@app.route("/download")
def download():
    if not os.path.exists(COMBINED_PATH):
        return "No combined file yet — run a batch first.", 404
    return send_file(COMBINED_PATH, as_attachment=True,
                     download_name="youtube_transcripts.txt")


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
  .wrap{max-width:760px;margin:0 auto;padding:28px 18px 60px}
  h1{font-size:22px;margin:0 0 4px;letter-spacing:-.3px}
  .sub{color:var(--muted);font-size:13px;margin:0 0 20px}
  textarea{width:100%;min-height:150px;background:var(--surface);border:1px solid var(--border);
    color:var(--text);border-radius:12px;padding:13px;font:14px/1.5 ui-monospace,SFMono-Regular,Menlo,monospace;resize:vertical;outline:none}
  textarea:focus{border-color:var(--accent)}
  .settings{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin:14px 0}
  .fld label{display:block;font-size:12px;color:var(--muted);margin:0 0 5px 2px;font-weight:600}
  input[type=number],input[type=text]{width:100%;background:var(--surface);border:1px solid var(--border);
    color:var(--text);border-radius:10px;padding:10px 11px;font-size:14px;outline:none}
  input:focus{border-color:var(--accent)}
  .chk{display:flex;align-items:center;gap:9px;background:var(--surface);border:1px solid var(--border);
    border-radius:10px;padding:10px 11px;font-size:14px;cursor:pointer;height:100%}
  .chk input{width:17px;height:17px;accent-color:var(--accent)}
  .row{display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin-top:6px}
  button{border:none;border-radius:11px;padding:12px 18px;font-size:15px;font-weight:700;cursor:pointer;
    color:#fff;background:var(--accent);transition:filter .15s,opacity .15s}
  button:hover{filter:brightness(1.08)} button:disabled{opacity:.5;cursor:default;filter:none}
  button.ghost{background:var(--surface);border:1px solid var(--border);color:var(--text)}
  .phase{margin:20px 0 10px;font-size:13px;color:var(--muted);min-height:18px}
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
</style></head>
<body><div class="wrap">
  <h1>YouTube Transcripts</h1>
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
    <button id="go">Get Transcripts</button>
    <button id="dl" class="ghost" disabled>Download combined file</button>
  </div>
  <div class="hint">Files are also saved to a <code>transcripts/</code> folder next to the app.</div>

  <div class="phase" id="phase"></div>
  <div id="summary"></div>
  <div class="list" id="list"></div>
</div>
<script>
const $=s=>document.querySelector(s);
const ICON={found:"✅",skipped:"⤬",failed:"✕",working:"…",pending:"•"};
let timer=null;
$("#go").onclick=async()=>{
  const text=$("#box").value;
  if(!text.trim()){alert("Paste at least one line first.");return;}
  $("#go").disabled=true;$("#dl").disabled=true;$("#summary").innerHTML="";$("#list").innerHTML="";
  const r=await fetch("/run",{method:"POST",headers:{"Content-Type":"application/json"},
    body:JSON.stringify({text,max:+$("#max").value||10,lang:$("#lang").value||"en",strip:$("#strip").checked})});
  const j=await r.json();
  if(!j.ok){alert(j.error||"Failed to start");$("#go").disabled=false;return;}
  poll();timer=setInterval(poll,1000);
};
$("#dl").onclick=()=>{location.href="/download";};
async function poll(){
  const s=await (await fetch("/progress")).json();
  $("#phase").textContent=s.phase+(s.running?" ":"");
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
      $("#dl").disabled=!s.combined;}
  }
}
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
