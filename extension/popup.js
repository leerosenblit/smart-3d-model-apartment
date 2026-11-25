const $ = (id) => document.getElementById(id)
const CATEGORIES = {
  sofa: 'ספה', armchair: 'כורסה', tv_unit: 'מזנון טלוויזיה', coffee_table: 'שולחן סלון', dining_table: 'שולחן אוכל',
  chair: 'כיסא', bed: 'מיטה', wardrobe: 'ארון', desk: 'שולחן עבודה', appliance: 'מוצר חשמל', lighting: 'תאורה',
  decor: 'עיצוב', other: 'אחר',
}
for (const [k, v] of Object.entries(CATEGORIES)) $('category').add(new Option(v, k))

let page = null // { url, html } of the tab being clipped

const server = () => $('server').value.trim().replace(/\/+$/, '')
const say = (el, text, cls = 'info') => {
  el.innerHTML = ''
  if (!text) return
  const d = document.createElement('div')
  d.className = `msg ${cls}`
  d.textContent = text
  el.appendChild(d)
}

async function post(path, body) {
  const r = await fetch(server() + path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
  if (!r.ok) throw new Error(`השרת החזיר ${r.status}`)
  return r.json()
}

async function activeTab() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true })
  return tab
}

function fill(parsed) {
  $('preview').hidden = false
  $('title').value = parsed.title || ''
  $('store').value = parsed.store_name || ''
  $('category').value = parsed.category || 'other'
  $('w').value = parsed.width_cm || ''
  $('d').value = parsed.depth_cm || ''
  $('h').value = parsed.height_cm || ''
  $('price').value = parsed.price_ils || ''
  $('image').value = parsed.image_url || ''
  $('img').src = parsed.image_url || ''
}

$('scan').onclick = async () => {
  say($('status'), 'סורק…')
  try {
    const tab = await activeTab()
    const [res] = await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      func: () => ({ url: location.href, html: document.documentElement.outerHTML }),
    })
    page = res.result
    await chrome.storage.local.set({ server: server() })
    const r = await post('/api/products/clip', { ...page, dry_run: true })
    fill(r.parsed)
    say(
      $('status'),
      r.missing.length ? `לא נמצאו: ${r.missing.join(', ')} — השלימו ידנית ושמרו` : 'נמצא הכול — בדקו ושמרו',
      r.missing.length ? 'err' : 'ok',
    )
  } catch (e) {
    say($('status'), `שגיאה: ${e.message}. האם השרת רץ ב-${server()}?`, 'err')
  }
}

$('save').onclick = async () => {
  if (!page) return
  const overrides = {
    title: $('title').value, store_name: $('store').value, category: $('category').value,
    width_cm: $('w').value, depth_cm: $('d').value, height_cm: $('h').value,
    price_ils: $('price').value, image_url: $('image').value,
  }
  try {
    const r = await post('/api/products/clip', { ...page, overrides })
    const text = r.status === 'failed' ? r.error : r.status === 'created' ? '✓ נוסף לקטלוג' : '✓ עודכן בקטלוג'
    say($('status'), text, r.status === 'failed' ? 'err' : 'ok')
  } catch (e) {
    say($('status'), `שגיאה: ${e.message}`, 'err')
  }
}

$('collect').onclick = async () => {
  const tab = await activeTab()
  const pattern = $('pattern').value.trim()
  const [res] = await chrome.scripting.executeScript({
    target: { tabId: tab.id },
    args: [pattern],
    func: (pat) => {
      const rx = pat ? new RegExp(pat) : /\/(product|products|p|item)\/|-p-|\d{5,}/i
      const out = new Set()
      for (const a of document.querySelectorAll('a[href]')) {
        let u
        try { u = new URL(a.href, location.href) } catch { continue }
        if (u.origin !== location.origin) continue
        u.hash = ''
        if (rx.test(u.pathname + u.search)) out.add(u.href)
      }
      return [...out]
    },
  })
  const list = res.result || []
  $('urls').value = list.join('\n')
  say($('batchStatus'), `נאספו ${list.length} קישורים — בדקו ועדכנו את הרשימה לפני הייבוא`)
}

$('batch').onclick = async () => {
  const urls = $('urls').value.split(/\s+/).map((u) => u.trim()).filter((u) => /^https?:\/\//.test(u))
  if (!urls.length) return say($('batchStatus'), 'אין קישורים', 'err')
  // ask for access to the store's origin(s) so the extension can fetch product pages with YOUR session
  const origins = [...new Set(urls.map((u) => new URL(u).origin + '/*'))]
  const granted = await chrome.permissions.request({ origins })
  if (!granted) return say($('batchStatus'), 'נדרשת הרשאה לגשת לאתר כדי לייבא', 'err')
  await chrome.storage.local.set({
    server: server(),
    batch: { total: urls.length, done: 0, ok: 0, failed: 0, errors: [], running: true },
  })
  chrome.runtime.sendMessage({ type: 'batch', urls, server: server() })
}
$('stop').onclick = () => chrome.runtime.sendMessage({ type: 'stop' })

function renderBatch(b) {
  if (!b) return
  $('bar').hidden = false
  $('bar').max = b.total || 1
  $('bar').value = b.done
  const lines = [`${b.running ? 'מייבא' : 'הסתיים'}: ${b.done}/${b.total} · הצלחות ${b.ok} · כשלונות ${b.failed}`]
  if (b.errors && b.errors.length) lines.push(...b.errors.slice(-3))
  say($('batchStatus'), lines.join('\n'), b.running ? 'info' : b.failed ? 'err' : 'ok')
}
chrome.storage.onChanged.addListener((c) => c.batch && renderBatch(c.batch.newValue))
chrome.storage.local.get(['server', 'batch']).then((s) => {
  if (s.server) $('server').value = s.server
  renderBatch(s.batch)
})
