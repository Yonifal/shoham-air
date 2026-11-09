/**
 * "מריח עשן" – residents' smoke reports for Shoham.
 * Paste into a Google Sheet: Extensions → Apps Script, then Deploy → New deployment →
 * type "Web app", Execute as: Me, Who has access: Anyone. Copy the /exec URL.
 *
 * POST  {hood, level, note}      → appends a row
 * GET   ?days=7                  → JSON of recent reports (no personal data is stored)
 */
const SHEET = "reports";
const HOODS = ["הדרים","יעלים","כרמים","טללים","סחלבים","חמניות","גבעולים","ברושים","יובלים","רקפות","אחר"];

function sheet_() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  let sh = ss.getSheetByName(SHEET);
  if (!sh) { sh = ss.insertSheet(SHEET); sh.appendRow(["time", "hood", "level", "note"]); }
  return sh;
}

function doPost(e) {
  let d = {};
  try { d = JSON.parse(e.postData.contents); } catch (err) { d = e.parameter || {}; }
  const hood = HOODS.indexOf(d.hood) >= 0 ? d.hood : "אחר";
  const level = Math.max(1, Math.min(3, parseInt(d.level, 10) || 1));
  const note = String(d.note || "").slice(0, 140);
  // light flood guard: max 120 reports per 10 minutes overall
  const cache = CacheService.getScriptCache();
  const n = parseInt(cache.get("n") || "0", 10);
  if (n > 120) return out_({ ok: false, error: "busy" });
  cache.put("n", String(n + 1), 600);
  sheet_().appendRow([new Date(), hood, level, note]);
  return out_({ ok: true });
}

function doGet(e) {
  const days = Math.min(400, parseInt((e && e.parameter.days) || "7", 10));
  const since = Date.now() - days * 864e5;
  const rows = sheet_().getDataRange().getValues().slice(1)
    .filter(r => r[0] instanceof Date && r[0].getTime() >= since)
    .map(r => ({ t: r[0].toISOString(), hood: r[1], level: r[2], note: r[3] }));
  return out_({ ok: true, reports: rows });
}

function out_(o) {
  return ContentService.createTextOutput(JSON.stringify(o)).setMimeType(ContentService.MimeType.JSON);
}
