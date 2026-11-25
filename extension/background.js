// Batch importer: fetches each product page with the user's own browser session (cookies, normal TLS
// fingerprint) and sends the HTML to the local RoomCraft server's /api/products/clip endpoint.
let stopRequested = false
let running = false
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

async function update(patch) {
  const { batch } = await chrome.storage.local.get('batch')
  await chrome.storage.local.set({ batch: { ...batch, ...patch } })
}

async function runBatch(urls, server) {
  if (running) return
  running = true
  stopRequested = false
  let done = 0
  let ok = 0
  let failed = 0
  const errors = []
  for (const url of urls) {
    if (stopRequested) break
    try {
      const page = await fetch(url, { credentials: 'include' })
      if (!page.ok) throw new Error(`HTTP ${page.status}`)
      const html = await page.text()
      const r = await fetch(`${server}/api/products/clip`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url, html }),
      })
      const result = await r.json()
      if (result.status === 'failed') throw new Error(result.error || 'נכשל')
      ok++
    } catch (e) {
      failed++
      errors.push(`${url.slice(0, 60)}… — ${e.message}`)
    }
    done++
    await update({ done, ok, failed, errors: errors.slice(-20), running: true })
    await sleep(1000 + Math.random() * 600) // be polite: about one page per second
  }
  running = false
  await update({ done, ok, failed, errors: errors.slice(-20), running: false })
}

chrome.runtime.onMessage.addListener((msg) => {
  if (msg.type === 'batch') runBatch(msg.urls, msg.server)
  if (msg.type === 'stop') stopRequested = true
})
