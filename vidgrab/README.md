# VidGrab

A single Windows `.exe` for downloading YouTube, TikTok, and Instagram videos —
with audio, without audio (video only), audio only, or as one JPEG frame per
second — at your choice of quality. It's a lightweight Go wrapper around
[yt-dlp](https://github.com/yt-dlp/yt-dlp), served as a local web UI.

## Using it

1. Run `VidGrab.exe`.
2. On first run it downloads `yt-dlp.exe`, `ffmpeg.exe`, and `aria2c.exe` into
   a `bin/` folder next to itself (one-time, needs internet, ~80MB mostly for
   ffmpeg). Subsequent runs are instant.
3. Your default browser opens to `http://127.0.0.1:8991`. Paste a video URL,
   pick a format (Video + Audio / Video only / Audio only / Frames) and
   quality (defaults to the best available), and click Download.
4. When the download finishes, your browser's own download flow kicks in
   automatically — the file lands wherever your browser is set to save
   downloads, just like downloading anything else from the web.

Audio-only downloads are extracted as MP3 at the best available quality.
Video downloads are merged to MP4 via ffmpeg.

## Frame mode

Pick **Frames (1/sec)** and VidGrab downloads the video, then uses ffmpeg to
split it into one JPEG per second of runtime. Instead of an automatic file
download, you get a page of large preview tiles (click one to zoom in full-size)
each with its own **Download** button, so you can pick exactly the frames you
want and download only those — nothing forces you to grab all of them.

## Download speed

Nothing can exceed your actual internet bandwidth, but yt-dlp's default of a
single connection per stream often falls well short of it — especially
against CDNs (like YouTube's) that throttle long single-connection transfers.
To close that gap, VidGrab always sets `--concurrent-fragments 8`, and uses
`aria2c` as an external multi-connection downloader (16 connections) whenever
it's available, which is the standard way to get yt-dlp close to your real
line speed. If `aria2c` can't be fetched on first run (no internet, GitHub
unreachable), VidGrab falls back to the built-in downloader automatically —
still faster than default, just not as fast as with aria2c.

## Building from source

Requires Go 1.21+. From this directory:

```bash
./build.sh
```

or directly:

```bash
GOOS=windows GOARCH=amd64 go build -ldflags "-s -w" -o VidGrab.exe .
```

This cross-compiles cleanly from Linux/macOS/Windows — no CGO or platform
toolchain is required since the app only shells out to `yt-dlp`/`ffmpeg` at
runtime rather than linking against them.

Run `go test ./...` to run the unit tests (format-selector construction,
frame-extraction orchestration against fake `yt-dlp`/`ffmpeg` scripts, and
progress-parsing logic).

## How it works

- `main.go` — HTTP server, embeds the UI (`web/index.html`), wires up the
  `/api/download`, `/api/progress` (Server-Sent Events), `/api/file`, and
  `/api/frame` endpoints. `/api/file` and `/api/frame?download=1` stream with
  a `Content-Disposition: attachment` header so the browser handles them as a
  normal download rather than VidGrab picking a folder for you; `/api/frame`
  without that flag serves a frame inline for the preview grid.
- `jobs.go` — builds `yt-dlp` format-selector and speed-related arguments per
  mode/quality and runs/tracks download jobs, parsing progress from
  `yt-dlp`'s stdout. yt-dlp writes into a `tmp/` staging folder (wiped on
  every startup) until the browser has picked it up. For Frames mode, once
  the video lands it's handed to `ffmpeg -vf fps=1` and the source video is
  deleted, keeping only the extracted JPEGs.
- `setup.go` — downloads `yt-dlp.exe`, `ffmpeg.exe`/`ffprobe.exe`, and
  `aria2c.exe` on first run if they're not already present in `bin/`.

## A note on usage

This tool only automates the publicly available `yt-dlp` extractor — it
doesn't circumvent DRM or access private content. Downloading content you
don't own or have rights to may violate the terms of service of
YouTube/TikTok/Instagram and, depending on your jurisdiction, copyright law.
Use it for content you have the right to download (your own uploads,
Creative Commons/public-domain material, or explicit permission from the
creator).
