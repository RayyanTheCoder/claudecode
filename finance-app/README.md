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
