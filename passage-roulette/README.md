# Passage Roulette

A tiny phone-first app for saving passages from books and pulling one at random.

Single `index.html` file — no build step, no framework, no dependencies. Data
lives in `localStorage`, so it works offline and stays on your device.

## Use it

Open `index.html` in any browser. On a phone, add it to your home screen for a
full-screen, offline app.

## Features

- **Random** — boots straight to a random passage; tap **Another** for the next one.
- **Add** — text, book, author, optional note, optional comma-separated tags, favourite toggle.
- **Library** — every passage, searchable by text / book / author / tag, with edit and delete.
- **Tag filter** — pull a random passage from a single tag instead of the whole set.
- **Favourites** — toggle per passage; scope random pulls to favourites only.
- **Export / Import JSON** — back up and move between devices from the Library tab.
- **Dark by default**, with a light toggle.

## Data model

Each passage is stored as:

```json
{
  "id": "unique string",
  "text": "the passage",
  "book": "title",
  "author": "author name",
  "note": "optional — why you saved it",
  "tags": ["array", "of", "strings"],
  "favorite": false,
  "dateAdded": "ISO date"
}
```

Export produces a JSON array of these objects. Import merges them in, keeping
existing entries and giving colliding IDs fresh ones.
