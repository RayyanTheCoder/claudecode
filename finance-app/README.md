# Pocket — Personal Finance App

A single-file, offline-first personal finance tracker rendered inside an Android
device frame. Open `index.html` in any browser — no build step, no server.

## Features

**Auth**
- Email / password sign up and sign in (accounts stored per-device in `localStorage`).
- **Continue with Google** — real Google Identity Services when configured
  (see below), otherwise a clearly-marked demo Google account so the flow works
  fully offline.
- Session persists across reloads; each account gets its own isolated data.

**Home tab**
- Date line + "Your money" header.
- Hero card with **Money left** as the headline figure, and a `+` that opens an
  inline field to set your **Total money baseline** (a manual adjustment).
- Two sub-stats: **Total money** (salary + commission + adjustment) and **Expenses**.
- **Income sources** row — tappable Salary and Commission cards showing running
  total and entry count; tapping opens the add form pre-set to that type.
- **Recent activity** with icon, label, `type · date`, signed amount, and
  "See all →" that jumps to History.

**History tab**
- Segmented filter: All / Salary / Commission / Expenses.
- Full entry list with per-row delete and tap-to-edit.
- **Bulk add** — paste many lines like `Groceries 42.50`, added at once as the
  active filter's type.
- **Export / Import** — download all data as JSON, or load a file / pasted JSON
  on another device.
- **Settings** — number of recent items shown on Home, and which tab opens by default.

**Core math**
```
Salary + Commission + Baseline = Total money
Total money − Expenses         = Money left
```
Everything recalculates live and auto-saves.

**Add / Edit dialog** — type selector (Salary / Commission / Expense), label,
amount, date, validation, and a Delete action when editing. Opened by the
floating `+`, which defaults to the type you're currently filtered to.

## Enabling real Google sign-in

1. In [Google Cloud Console](https://console.cloud.google.com/apis/credentials),
   create an **OAuth 2.0 Client ID** of type *Web application*.
2. Add your serving origin (e.g. `https://yourdomain.com`) to
   **Authorized JavaScript origins**.
3. Set the client id in `index.html`:
   ```html
   <script>window.GOOGLE_CLIENT_ID = "YOUR_CLIENT_ID.apps.googleusercontent.com";</script>
   ```

Left as `null`, the app uses a demo Google account so nothing is blocked offline.

## Notes

Passwords use a lightweight non-cryptographic hash — this is a client-side demo,
not a production auth system. Data lives in the browser's `localStorage`; use
Export / Import to move it between devices.

## Installable PWA

This folder is a self-contained installable PWA:

- `manifest.webmanifest` — name, short name, standalone display, theme/background
  colours, start URL, and PNG icons.
- `sw.js` — cache-first service worker that precaches the app shell, so it works
  fully offline after the first load.
- Icons — `icon-192.png`, `icon-512.png`, `icon-512-maskable.png`, and a 180px
  `apple-touch-icon.png` for the iOS home screen. A favicon is inlined in the
  `<head>` so a bare load never 404s.
- Service-worker registration is guarded to run only over `http(s)`, so opening
  `index.html` straight from disk (`file://`) still works.
- **Update handling** — on load the app detects a newly deployed service worker
  and shows a *"New version available — tap to refresh"* prompt. Tapping it calls
  `skipWaiting()` and reloads, so you never have to clear the cache after a deploy.
  Bump the `CACHE` constant in `sw.js` on each deploy to trigger it.

### Deploy (GitHub Pages)

Served with GitHub Pages' **Deploy from a branch** mode — no build step:

1. Repo **Settings → Pages → Build and deployment**.
2. **Source:** *Deploy from a branch*.
3. **Branch:** the branch this lives on, folder **/ (root)** → **Save**.

The site publishes at `https://<user>.github.io/<repo>/`; the root `index.html`
redirects a bare URL to `./finance-app/`. Bump the `CACHE` constant in `sw.js`
on each deploy so clients pick up the new version via the update prompt.

Run locally over http (needed for the service worker):

```bash
cd finance-app && python3 -m http.server 8000   # then open http://localhost:8000
```
