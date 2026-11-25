# RoomCraft 3D — Floorplan & Real-Furniture Interior Designer

## Project Overview
RoomCraft 3D is a fullstack web application that lets users upload an architectural floorplan (image or PDF), calibrate scale and trace walls/openings, browse a local database of pre-scraped real furniture and appliances (with accurate cm dimensions and ILS prices), drag items into the apartment, and design in real-time 2D/3D with a live budget tracker.

3D models (`.glb`) are generated **lazily** via an Image-to-3D API only when a user drags an item into a room for the first time, then cached locally on disk and referenced in SQLite so subsequent uses are instant and free.

## Tech Stack
- **Frontend:** React 18+, TypeScript (strict), Vite, Tailwind CSS, Zustand (state management), React Three Fiber (`@react-three/fiber`, `@react-three/drei`, `three`).
- **Backend:** Python 3.12, FastAPI, SQLModel + SQLite, Pydantic v2, `httpx`, `beautifulsoup4`, `trimesh` (for mock/procedural GLB fallback), `pymupdf` (optional PDF floorplan rendering to PNG).
- **AI / External Integrations (Pluggable via `.env`):**
  - **Image-to-3D:** `Tripo3DProvider` (Tripo v2 API), `MeshyProvider` (Meshy API), and `MockGlbProvider` (automatic zero-cost fallback when no API key is configured).
  - **Smart Product Extraction:** Structured HTML parser (JSON-LD / OpenGraph / regex) with optional LLM extraction fallback (`ANTHROPIC_API_KEY` or `OPENAI_API_KEY`) for extracting Hebrew/English dimensions and prices from arbitrary store pages.
- **Storage:** Local filesystem (`backend/storage/floorplans/` and `backend/storage/models/`) served via FastAPI static routes.

## Repository Structure
```text
/
├── CLAUDE.md
├── .env.example
├── Makefile / dev.sh
├── frontend/
│   ├── src/
│   │   ├── api/                # Typed API client for backend endpoints
│   │   ├── components/
│   │   │   ├── editor2d/       # Floorplan overlay, scale calibration, wall/opening drawing, ruler
│   │   │   ├── viewer3d/       # R3F Canvas, wall extrusion with cutouts, furniture meshes, gizmos
│   │   │   ├── catalog/        # Searchable/filterable sidebar, URL importer modal, live BOM/budget
│   │   │   └── layout/         # Top toolbar, 2D/3D/Split view switcher, save/load project modals
│   │   ├── store/              # Single Zustand store (scene + catalog + UI state + undo/redo)
│   │   ├── utils/              # Unit conversion (cm <-> m), normalizeGlbModel, wall snapping, geometry
│   │   └── types/              # Shared TypeScript interfaces matching backend schemas
└── backend/
    ├── app/
    │   ├── main.py             # FastAPI app, CORS, static mounts, lifespan DB init
    │   ├── config.py           # Pydantic Settings loading .env
    │   ├── db.py               # SQLite engine & session dependency
    │   ├── models.py           # SQLModel DB tables (Product, Project)
    │   ├── schemas.py          # Pydantic request/response models
    │   ├── routers/            # products.py, projects.py, floorplans.py, generation.py
    │   └── services/
    │       ├── scraper.py      # URL/batch fetcher + JSON-LD/HTML + optional LLM dimension extractor
    │       └── model_3d.py     # Abstract ImageTo3DProvider + Tripo3D + Meshy + MockGlbProvider
    ├── scripts/
    │   ├── seed.py             # Seeds realistic furniture/appliance catalog
    │   └── ingest.py           # CLI batch scraper from a list of URLs or JSON file into SQLite
    ├── tests/                  # Pytest suite covering API, scraper parser, and lazy 3D flow
    └── storage/                # Uploaded floorplans & cached .glb files
```

## Core Architectural Rules (Non-Negotiable)

### 1. Canonical Units & Single Source of Truth
- **All persisted and state data MUST be in centimeters (`cm`)**: wall endpoints, thicknesses, ceiling height (`270` cm default), opening widths/heights/sill heights, product dimensions (`width_cm`, `depth_cm`, `height_cm`), and placed item coordinates (`x_cm`, `z_cm`).
- **Meters conversion happens ONLY inside the Three.js / R3F rendering layer** (`value / 100`). Never store meters in Zustand or SQLite.
- **Single Scene State:** Both the 2D Editor and 3D Viewer render directly from the exact same Zustand scene state (`walls`, `openings`, `placedItems`, `ceilingHeightCm`). Never duplicate scene state between 2D and 3D.

### 2. 3D Model Normalization & Floor Pivot Rule
Image-to-3D models return arbitrary scales and origin points. Every loaded `.glb` MUST pass through `normalizeGlbModel(scene, { width_cm, depth_cm, height_cm })`:
1. Clone/wrap the loaded GLTF scene and compute `THREE.Box3().setFromObject(object)`.
2. Scale along X, Y, Z to match exact real-world dimensions in meters (`width_cm / 100`, `height_cm / 100`, `depth_cm / 100`).
3. Recenter X and Z to `0`, and offset Y so `box.min.y === 0` (bottom-center pivot sitting strictly flush on the floor plane `y = 0`).

### 3. Lazy 3D Generation & Caching Flow
- Products in SQLite begin with `model_3d_url = null` and `model_status = "none"`.
- When a user drags a product into the floorplan/3D scene:
  1. Immediately place an exact-dimension translucent placeholder box (with wireframe + Hebrew title + subtle loading badge) so layout and spacing work instantaneously.
  2. If `model_3d_url` is `null` and `model_status` is `"none"` or `"failed"`, call `POST /api/products/{id}/generate-3d`.
  3. Backend runs generation asynchronously via FastAPI `BackgroundTasks`, downloads/writes the `.glb` to `backend/storage/models/{id}.glb`, and updates `model_3d_url = "/static/models/{id}.glb"` and `model_status = "ready"`.
  4. Frontend polls `GET /api/products/{id}/3d-status` until `"ready"`, then hot-swaps the placeholder with the normalized `.glb` without losing position, rotation, or selection.
- Repeated drags of the same product reuse the cached `.glb` immediately with zero API calls.

### 4. Pre-Scraped Catalog Database Schema
- **`products` table:**
  - `id` (int PK)
  - `store_name` (str)
  - `product_url` (str, unique index)
  - `title` (str)
  - `category` (str: `sofa`, `armchair`, `tv_unit`, `coffee_table`, `dining_table`, `chair`, `bed`, `wardrobe`, `desk`, `appliance`, `lighting`, `decor`, `other`)
  - `price_ils` (float)
  - `width_cm` (float)
  - `depth_cm` (float)
  - `height_cm` (float)
  - `image_url` (str)
  - `model_3d_url` (Optional[str])
  - `model_status` (str: `none | generating | ready | failed`)
  - `model_error` (Optional[str])
  - `updated_at` (datetime)
- **`projects` table:**
  - `id` (int PK)
  - `name` (str)
  - `floorplan_image_url` (Optional[str])
  - `pixels_per_cm` (Optional[float])
  - `scene_json` (JSON text: `{ ceilingHeightCm, walls, openings, placedItems }`)
  - `updated_at` (datetime)

## Coding & UI Conventions
- **Code language:** English only for all files, identifiers, types, API fields, comments, and commits.
- **UI language:** Clean, modern **Hebrew RTL interface** (`dir="rtl"` on UI chrome, `₪` price formatting, cm labels), keeping canvas/3D coordinate math completely decoupled from RTL CSS.
- **Resilience:** Graceful fallbacks everywhere — if no external API keys are set in `.env`, the entire app (including catalog browsing, URL metadata parsing, and lazy 3D generation via `MockGlbProvider`) MUST work out of the box locally.