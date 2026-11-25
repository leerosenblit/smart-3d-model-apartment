# RoomCraft Clipper (browser extension)

Send products from **any** store page to your local RoomCraft 3D catalog — including stores the automatic
crawler cannot reach (bot protection, login walls, JavaScript-only pages). It runs inside *your* browser, so the
store just sees a normal visit.

## Install (Chrome / Edge / Brave, ~30 seconds)
1. Make sure RoomCraft is running (`start.bat` or `./dev.sh`) — the API must answer on `http://127.0.0.1:8000`.
2. Open `chrome://extensions` and switch on **Developer mode**.
3. Click **Load unpacked** and select this `extension/` folder.
4. Pin the extension (puzzle icon → pin).

## Use
- **One product:** open the product page → click the extension → **סרוק את הדף**. Check/fix the fields (the
  server reads JSON-LD, OpenGraph and Hebrew/English dimension text) → **שמור בקטלוג**. If dimensions are not on the
  page, type them in (in cm) from the spec sheet.
- **Many products:** open a category/listing page → **אסוף קישורים מהדף** (optionally give a regex for the product
  link pattern) → trim the list → **ייבא הכל**. The extension asks once for access to that store, then opens each
  page with your session, about one per second, and clips it. You can close the popup; it keeps running.

Nothing leaves your machine except the page requests your browser would make anyway.
