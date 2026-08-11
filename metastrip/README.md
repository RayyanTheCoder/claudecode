# MetaStrip — on-device video metadata remover

Strip identifying metadata from short-form video clips **entirely in the browser**.
Files never leave the device — there is no server, no upload, and no account. Works
offline and installs to a phone home screen as a PWA.

## What it removes

Using a container rewrite with a **stream copy** (`-map_metadata -1 -c copy`), so the
video and audio streams are byte-for-byte preserved — **no re-encoding, no quality loss**:

- Creation / modification timestamps
- GPS / location tags
- Device and software identifiers
- Encoder tags (and, for mp4/mov, the muxer's own encoder/date via `-fflags +bitexact`)
- Custom / user-defined tags, chapters, and per-stream metadata

> **Container note:** WebM/Matroska mandates a `WritingApp` element, so scrubbed `.webm`
> files keep a bare `encoder: Lavf` marker (no version, non-identifying). This is inherent
> to the format. **mp4/mov output is stripped completely.**

## How it works

- **ffmpeg.wasm** runs the strip inside a Web Worker, so the UI never blocks.
- The engine is **lazy-loaded** — the app shell opens in well under a second; the ~32 MB
  ffmpeg core is only fetched on the first *Process*, then cached for offline reuse.
- Batch processing runs **sequentially** (to stay within browser memory) with per-file and
  overall progress, throughput, and **continue-on-failure** — one bad file never stops the run.
- **Download all** bundles multiple outputs into a `.zip` (STORE method — video is already
  compressed) using a small self-contained writer, so nothing is fetched from a third party.

## Features

- Drag & drop, multi-select file picker, and whole-folder drop (where the browser allows).
- Queue with per-file status, progress, individual download, remove, and retry.
- Optional **before / after** metadata comparison to confirm the strip worked.
- Optional filename suffix (e.g. `clip.mp4` → `clip-clean.mp4`).
- Large-file warnings when a file is likely to strain in-browser (wasm) memory.
- Dark / light theme, haptic feedback on completion, installable PWA, fully offline.

## Privacy

No uploads. No analytics. No external network calls at runtime — the ffmpeg engine is
**vendored locally** under `vendor/` and served same-origin.

## Layout

```
index.html                 the whole app (single file)
manifest.webmanifest       PWA manifest
sw.js                      service worker (offline shell + runtime cache)
icons/                     192 / 512 / maskable / apple-touch / favicon
vendor/                    ffmpeg.wasm 0.12 (ffmpeg + util + core), UMD builds
gen_icons.py               regenerates the icons
```
A root-level `../index.html` redirects a bare URL to this folder.

## Running

It is static — serve the folder over HTTP (a service worker needs an origin):

```sh
python3 -m http.server 8080   # then open http://localhost:8080/metastrip/
```

Browser support: any recent Chromium/Firefox/Safari with WebAssembly. Single-threaded
ffmpeg core is used, so **no cross-origin-isolation headers (COOP/COEP) are required** —
it works on plain static hosts like GitHub Pages.

## Regenerating assets

```sh
python3 gen_icons.py          # icons (needs Pillow)
```
The `vendor/` files come from the `@ffmpeg/ffmpeg@0.12.10`, `@ffmpeg/util@0.12.1`, and
`@ffmpeg/core@0.12.6` npm packages (UMD builds).
