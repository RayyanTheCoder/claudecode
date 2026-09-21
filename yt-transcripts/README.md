# YouTube Transcript Tool (local)

A tiny local web app that grabs transcripts from a mixed batch of YouTube links.
Paste a batch, hit one button, watch each item resolve, and download one combined
`.txt` at the end. Everything runs on your Mac — nothing is uploaded anywhere.

## What each line can be (auto-detected)

| You paste… | It does… |
|---|---|
| a video URL | grabs that video's transcript |
| a channel URL (`/@handle`, `/channel/…`, `/c/…`, `/user/…`) | lists its uploads and grabs each |
| a playlist URL (`…playlist?list=…`) | lists the playlist and grabs each |
| plain text | treats it as a YouTube search and takes the **top result** |

Mix them freely — one line each, all handled in one run.

## Setup & run (macOS)

Open **Terminal**, then:

```bash
cd yt-transcripts          # the folder this README is in
bash run.sh                # one command: sets up everything and launches
```

That creates a virtual environment, installs the dependencies, and opens
**http://127.0.0.1:7654** in your browser.

<details><summary>Prefer to do it by hand?</summary>

```bash
cd yt-transcripts
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```
</details>

To stop it: press **Ctrl + C** in Terminal. To run it again later, just
`bash run.sh` (it reuses the environment, so it's fast).

## Using it

1. Paste your batch into the big box — one item per line.
2. (Optional) set **Max videos per channel/playlist** (default 10),
   **Language** (default `en`), and **Strip timestamps** (default on).
3. Click **Get Transcripts**. Each item shows up as **found**, **skipped**
   (no captions available), or **failed** (with the reason).
4. When it finishes, click **Download combined file**.

## Output

Saved into a `transcripts/` folder next to the app:

- **One `.txt` per video**, named by the video title, with the title and URL at the top.
- **`_ALL_transcripts.txt`** — every transcript under a clear `### title / URL`
  header, with a summary at the very top (how many found / skipped / failed).
  This is what the **Download** button gives you.

## How it works

- **`yt-dlp --flat-playlist`** lists videos from channels and playlists *without*
  downloading anything.
- **`youtube-transcript-api`** fetches each transcript — **manual captions first**,
  auto-generated as a fallback (and will translate to your language if that's all
  that's available).
- Videos with no transcript are **skipped** and shown in the list.
- A short delay (~1.2s) is added between requests so YouTube doesn't rate-limit you.

## Notes

- Data and files stay on your machine.
- If a channel is huge, the **Max videos** setting caps how many it pulls.
- If YouTube temporarily blocks requests (too many, too fast), wait a bit and
  re-run — the delay is there to avoid this.
- Change the port with `PORT=8080 bash run.sh` if `7654` is taken.
