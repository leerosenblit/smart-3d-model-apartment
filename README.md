# RoomCraft 3D

Upload a floorplan, calibrate its scale, trace walls and openings, drag real furniture (real cm dimensions, ₪ prices) into the apartment, and design in synchronized 2D/3D with a live budget. Hebrew RTL UI.

3D models are generated **lazily**: the first time you place a product, an exact-size translucent placeholder appears instantly, a `.glb` is generated in the background, cached on disk, and hot-swapped in place. Later placements reuse the cached model with zero API calls.

**Works out of the box with no API keys** — seeded catalog, procedural mock GLBs, regex/JSON-LD product extraction.

## Quick start

Requirements: Python 3.12, Node 20+.

```bash
./dev.sh          # Linux/macOS/Git Bash: creates venv, installs deps, starts both servers
```
```powershell
.\dev.ps1         # Windows PowerShell equivalent
```

- App: <http://localhost:5173> · API docs: <http://localhost:8000/docs>
- The catalog is auto-seeded (23 products) on first startup.

Manual setup:

```bash
python -m venv backend/.venv && backend/.venv/bin/pip install -r backend/requirements.txt   # Windows: backend\.venv\Scripts\
cd backend && ../backend/.venv/bin/python -m uvicorn app.main:app --reload --port 8000
cd frontend && npm install && npm run dev
```

## Configuration (`.env`, all optional — see `.env.example`)

| Variable | Purpose |
|---|---|
| `IMAGE_TO_3D_PROVIDER` | `mock` (default) \| `tripo3d` \| `meshy`. Falls back to `mock` if the key is missing. |
| `TRIPO_API_KEY` / `MESHY_API_KEY` | Real image-to-3D. Needs products with a public `http(s)` image URL (seed products use local SVG thumbnails, so they fail with a clear error under real providers — use imported products). |
| `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` | LLM fallback for the URL importer — called only when dimensions/price/category can't be parsed. |

## Using the app

1. **Upload floorplan** (PNG/JPG/WebP/BMP/GIF/TIFF/PDF — PDFs are rendered to PNG at 200 DPI, page 1). Walls, doors and windows are **detected automatically** and the 3D model appears at once. The scale is first *estimated* from the typical wall thickness (~20 cm); for exact sizes **calibrate** (click two points, type the real length in cm) and detection re-runs at the exact scale. Detection is heuristic (see below) — fix mistakes in 2D, or use **🪄 זיהוי קירות אוטומטי** to re-run it.
2. **Walls**: click to draw (90° snap, endpoint snap, Enter/double-click to finish). **Openings**: pick door/window, click a wall; edit width/height/sill in the panel. **Ruler**: measure any distance.
3. **Furniture**: drag cards from the catalog into the 2D *or* 3D view (or press **הוסף**). Drag to move (grid + wall snapping, `Alt` disables), rotate (90° button, slider, or 2D handle), duplicate, delete. Orange labels show live clearance (cm) to walls/items.
4. **Import** store URLs (one per line) or add products manually; **Budget** tab lists items with store links and exports CSV.
5. **Save/Load** projects (SQLite). Shortcuts: `Ctrl+Z/Y`, `Delete`, `R`, `Ctrl+D`, `Esc`, `Space`+drag to pan.

CLI ingestion: `cd backend && python -m scripts.ingest urls.txt` (one URL per line, or a JSON list of URLs / product objects). Re-seed: `python -m scripts.seed`.

## Catalog: crawler, thumbnails, extension

The seed catalog (23 placeholder products) is only an offline fallback. For a real catalog run the crawler from `backend/`:

```bash
python -m scripts.crawl_catalog                     # all stores; resumable (--resume), per store (--store ikea,ace,homecenter,shilav,...)
python -m scripts.warm_thumbs                       # pre-cache product photos so cards load instantly
python -m scripts.recategorize                      # split old 'wardrobe' rows into wardrobe / storage (update-only)
```

It reads IKEA Israel (sitemaps + JSON-LD), ACE (sitemap + page text) and HomeCenter / Shilav / small Shopify stores (`/products.json`), honours robots.txt, stays at 3–4 requests per host with delays, and keeps only rows with a real photo, a price and sane cm dimensions (accessories, covers and parts are filtered out; colour variants are capped). Photos are served resized and cached through `GET /api/products/{id}/image`. Stores that block automated access can be added with the **browser extension** in `extension/` (see its README): it sends the page you are looking at to `POST /api/products/clip`.

## Auto-build from a floorplan, and walk-through

Uploading a plan builds the whole apartment by default:

1. **Walls, doors, windows** (`backend/app/services/wall_detect.py`, numpy + Pillow, no ML model): colour/darkness mask → morphological closing → opening with thick-and-long rectangles (drops text, dimension lines, furniture, door arcs) → connected components → centre-line walls. A second pass finds **hollow partitions** (two thin parallel lines) and single thin lines that connect two walls. Collinear walls across 45–360 cm gaps become one wall with a door (≤110 cm), window, or patio door (>200 cm); wall ends snap to perpendicular walls. The **scale is estimated** from the typical wall thickness (~20 cm) until you calibrate.
2. **Rooms** are derived from the walls (see below), then **typed and named in Hebrew** (`frontend/src/utils/roomTyping.ts`): room names printed on the plan are read with **Tesseract OCR when it is installed with Hebrew data** (optional; e.g. "ח.שינה", "ח.רחצה", "פ.אוכל"), otherwise size/shape/door heuristics decide (bedroom, master, living room, bathroom, hallway, laundry, ...). Each type gets a default floor (parquet for bedrooms/living, tiles for bathrooms/kitchen/balcony).
3. **Auto-furnish** (`autoFurnish.ts`, toggle "ריהוט אוטומטי", button "🛋 רהט"): picks suitable real products from the catalog and places them — bed with the headboard on a wall plus bedside tables, wardrobe in a corner, desk, TV unit with the sofa facing it and a coffee table, a dining table with chairs in the roomiest spot — never blocking doors or overlapping. Placing products triggers lazy 3D generation (free with the mock provider; with a paid provider each distinct product is one generation).

**Bathrooms and balconies.** Bathrooms/toilets/laundry get built-in **preview-only 3D fixtures** (bathtub or shower, toilet, vanity sink, washing machine): they are not catalog products, have no price and never appear in the budget or shopping list. A **balcony** is an open-air area walled on three sides behind a wide door or window of an indoor room: it gets a tile floor, a glass railing along the open edge (solid in walk mode, so you cannot step off), and a small table with chairs. Furniture placement checks the exact wall shapes, so nothing ends up inside a wall.

Every result is editable (click a room to change its type, name or floor; drag furniture) and undoable. The detector targets axis-aligned walls: diagonal/curved walls, hatched open balconies and hand sketches may need a manual fix in 2D. Research systems use trained segmentation models (CubiCasa5K-style) or fine-tuned vision-language models for the hard cases; they need heavy dependencies/weights, so they are not bundled.

**Walk mode** (`🚶 הליכה בדירה`, or double-click the floor): first-person camera at 160 cm eye height. `W A S D`/arrows move, mouse looks (click to capture, `Esc` releases), `Shift` runs, `Q`/`E` turn. Walls and furniture block you; doors are passable; windows are solid.

## Rooms and floors

Rooms are **derived from the walls** (`frontend/src/utils/rooms.ts`), never stored: wall footprints are rasterised, the outside is flood-filled using a heavily gap-closed copy (so a few missed wall segments do not make rooms leak outside), cells enclosed on all four sides are rescued as indoors, and each enclosed region becomes a room with an area. An open-air area walled on three sides behind a wide door or window is a **balcony** (tile floor, glass railing that is solid in walk mode, outdoor furniture). Each room gets a procedural floor (parquet oak/walnut, tiles, concrete, carpet; `floorMaterials.ts`) painted into one canvas texture shared by the 2D editor and the 3D viewer. Click a room to change its type, name or floor; choices are saved with the project (`roomStyles`). Walls get baseboards in 3D. Bathrooms and the laundry room get built-in **preview-only fixtures** (tub or shower, toilet, vanity sink, washing machine): not products, no price, never in the budget or shopping list. Furniture placement checks the exact wall shapes, so nothing ends up inside a wall.

## 3D models

Models are generated **lazily** the first time a product is placed (never pre-generated), then cached in `backend/storage/models/`. The default **built-in modeller** (`backend/app/services/procedural.py`, no API key, free) builds a recognisable model per product: soft rounded cushions and pillows, L-shaped sectional sofas, beds with headboards and duvets, tapered legs, door panels with handles, open bookcases with books, chests of drawers, real appliance details (fridge, washer porthole, oven window), lamps with shades, rugs, mirrors and plants. Style variants (legs, arms, handles, headboard type, ...) are chosen per product and colours are read from the product photo, so products do not all look alike. Review every type side by side with `python -m scripts.model_gallery` and open `http://localhost:5173/?gallery` (dev server only).

For models that match each photo exactly, set `IMAGE_TO_3D_PROVIDER=tripo3d|meshy` and the matching key in `.env` (paid per model, only for products you actually place). Use **🔄 מודל חדש** on a selected item, or **🔄 רענן מודלים** in the 2D toolbar, to regenerate models cached by an earlier provider or an older version of the modeller.

## Architecture

- **Units**: everything persisted/in state is **centimeters**; meters exist only inside the R3F layer (`value / 100`). Plan `y` maps to world `z`.
- **One scene store** (`frontend/src/store/useAppStore.ts`) feeds both the SVG 2D editor and the R3F viewer; undo/redo snapshots the scene (one entry per drag gesture).
- `normalizeGlbModel` scales every GLB to the DB's exact W×D×H with a bottom-center pivot on `y = 0`.
- Backend: FastAPI + SQLModel/SQLite; generation runs in `BackgroundTasks`, status polled via `GET /api/products/{id}/3d-status`.

```
backend/app/{main,config,db,models,schemas}.py   routers/   services/{scraper,model_3d,seed_data}.py
backend/scripts/{seed,ingest}.py                 tests/     storage/{floorplans,models}
frontend/src/{api,components/{editor2d,viewer3d,catalog,layout},store,utils,hooks,types}
```

## Tests & checks

```bash
cd backend && python -m pytest -q      # CRUD, filters, seed, scraper, lazy 3D (mock + mocked Tripo/Meshy), uploads
cd frontend && npx tsc --noEmit && npm test && npm run build
```

Seed product URLs/images are illustrative placeholders, not live store links. The Tripo/Meshy/LLM integrations are covered by mocked-transport tests only (no live API calls were made).
