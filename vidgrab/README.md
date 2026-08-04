# VidGrab

A single Windows `.exe` for downloading YouTube, TikTok, and Instagram videos —
with audio, without audio (video only), or audio only — at your choice of
quality. It's a lightweight Go wrapper around [yt-dlp](https://github.com/yt-dlp/yt-dlp),
served as a local web UI.

## Using it

1. Run `VidGrab.exe`.
2. On first run it downloads `yt-dlp.exe` and `ffmpeg.exe` into a `bin/`
   folder next to itself (one-time, needs internet). Subsequent runs are
   instant.
3. Your default browser opens to `http://127.0.0.1:8991`. Paste a video URL,
   pick a format (Video + Audio / Video only / Audio only) and quality, and
   click Download.
4. Files are saved to `%USERPROFILE%\Downloads\VidGrab`. Click "Show file"
   after a download finishes to reveal it in Explorer.

Audio-only downloads are extracted as MP3 at the best available quality.
Video downloads are merged to MP4 via ffmpeg.

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

Run `go test ./...` to run the unit tests (format-selector construction and
progress-parsing logic).

## How it works

- `main.go` — HTTP server, embeds the UI (`web/index.html`), wires up the
  `/api/download`, `/api/progress` (Server-Sent Events), and
  `/api/open-folder` endpoints.
- `jobs.go` — builds `yt-dlp` format-selector arguments per mode/quality and
  runs/tracks download jobs, parsing progress from `yt-dlp`'s stdout.
- `setup.go` — downloads `yt-dlp.exe` and `ffmpeg.exe`/`ffprobe.exe` on first
  run if they're not already present in `bin/`.

## A note on usage

This tool only automates the publicly available `yt-dlp` extractor — it
doesn't circumvent DRM or access private content. Downloading content you
don't own or have rights to may violate the terms of service of
YouTube/TikTok/Instagram and, depending on your jurisdiction, copyright law.
Use it for content you have the right to download (your own uploads,
Creative Commons/public-domain material, or explicit permission from the
creator).
