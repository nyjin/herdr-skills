//! Scripts peek runs in the page through `evaluateJavaScript` (page scripts are off). Each evaluates to a JSON
//! string. A script that takes arguments has the shape `(function (a) { ... })(<JSON>)`: the body is a constant
//! and everything that comes from outside (query text, coordinates, marker) is a JSON value, never code.

#[derive(Clone, Debug, Default, PartialEq)]
pub struct FindQuery {
    pub text: String,
    pub case: bool,
    pub word: bool,
    pub regex: bool,
}

/// A word character for "whole word": any letter, combining mark or digit (not only ASCII), or `_`.
const WORD_CHAR: &str = r"[\p{L}\p{M}\p{N}_]";

/// Searches the page's text as one string, so a match may span elements (highlighted source puts every token in
/// its own span); a line break stands between blocks. `window.peekFind` keeps the text (collected once per page:
/// page scripts are off, so the DOM does not change), the last query's matches, and the marked window: at most
/// `LIMIT` matches around the current one are marked, and stepping inside that window only moves the current mark.
const FIND: &str = r#"function (a) {
  const LIMIT = 10000;
  const SKIP = 'script, style, noscript, template, td.n';
  const BLOCK = 'address, article, aside, blockquote, body, dd, details, div, dl, dt, fieldset, figcaption, figure, '
    + 'footer, form, h1, h2, h3, h4, h5, h6, header, hr, li, main, nav, ol, p, pre, section, summary, table, td, '
    + 'th, tr, ul';
  const unmark = () => { CSS.highlights.delete('peek-find'); CSS.highlights.delete('peek-cur'); };
  let st = window.peekFind;
  if (!st) {
    const nodes = [], starts = [], parts = [];
    let len = 0, last = null;
    const walk = document.createTreeWalker(document.body || document.documentElement,
      NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT,
      { acceptNode: (n) => n.nodeType === 1 && n.matches(SKIP) ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT });
    for (let n = walk.nextNode(); n; n = walk.nextNode()) {
      if (n.nodeType !== 3 || !n.data) continue;
      const block = n.parentElement.closest(BLOCK);
      if (block !== last && len) { parts.push('\n'); len += 1; }
      last = block;
      nodes.push(n); starts.push(len); parts.push(n.data); len += n.data.length;
    }
    st = window.peekFind = { nodes, starts, text: parts.join(''), src: null, flags: null, ms: [], all: null, lo: 0 };
  }
  if (st.src !== a.src || st.flags !== a.flags) {
    unmark();
    st.src = null; st.ms = []; st.all = null;
    if (!a.src) return JSON.stringify([0, 0, -1]);
    let re;
    try { re = new RegExp(a.src, a.flags); } catch (e) { return JSON.stringify([-1, 0, -1]); }
    for (const m of st.text.matchAll(re)) {
      if (m[0].length) st.ms.push(m.index, m.index + m[0].length);
    }
    st.src = a.src; st.flags = a.flags;
  }
  const count = st.ms.length / 2;
  if (!count) return JSON.stringify([0, 0, -1]);
  const at = (off, end) => {
    let lo = 0, hi = st.starts.length - 1;
    while (lo < hi) { const mid = (lo + hi + 1) >> 1; if (st.starts[mid] <= off) lo = mid; else hi = mid - 1; }
    const n = st.nodes[lo], o = off - st.starts[lo];
    if (o <= n.data.length) return [n, o];
    return end ? [n, n.data.length] : [st.nodes[lo + 1], 0];
  };
  const range = (k) => {
    const r = new Range(), s = at(st.ms[2 * k], false), e = at(st.ms[2 * k + 1], true);
    r.setStart(s[0], s[1]); r.setEnd(e[0], e[1]);
    return r;
  };
  const i = ((a.index % count) + count) % count;
  if (!st.all || i < st.lo || i >= st.lo + LIMIT) {
    st.lo = Math.max(0, Math.min(i - LIMIT / 2, count - LIMIT));
    st.all = new Highlight();
    for (let k = st.lo; k < Math.min(count, st.lo + LIMIT); k++) st.all.add(range(k));
    CSS.highlights.set('peek-find', st.all);
  }
  const cur = range(i);
  const strong = new Highlight(cur);
  strong.priority = 1;
  CSS.highlights.set('peek-cur', strong);
  return JSON.stringify([count, i, Math.round(cur.getBoundingClientRect().top + window.scrollY)]);
}"#;

/// Removes the marks and forgets the query; the page's collected text stays for the next search.
const FIND_CLEAR: &str = "(() => { CSS.highlights.delete('peek-find'); CSS.highlights.delete('peek-cur'); \
                          const st = window.peekFind; if (st) { st.src = null; st.ms = []; st.all = null; } \
                          return JSON.stringify(null); })()";

const HIT: &str = r#"function (a) {
  const e = document.elementFromPoint(a.x, a.y);
  const link = e && e.closest('a[href]');
  if (!link) return JSON.stringify(null);
  const raw = link.getAttribute('href');
  if (raw.startsWith('#')) return JSON.stringify(raw);
  try { return JSON.stringify(new URL(raw, document.baseURI).href); } catch (err) { return JSON.stringify(raw); }
}"#;

/// The first element under the middle of the viewport, scanning down from the top past margins; the offset is how
/// far the viewport top lies into it, as a fraction of its height, so it survives a re-layout.
const ANCHOR: &str = r#"(() => {
  const all = document.getElementsByTagName('*');
  for (let y = 1; y < window.innerHeight; y += 8) {
    const e = document.elementFromPoint(window.innerWidth / 2, y);
    if (!e || e === document.body || e === document.documentElement) continue;
    const r = e.getBoundingClientRect();
    if (r.height > 0) return JSON.stringify([Array.prototype.indexOf.call(all, e), -r.top / r.height]);
  }
  return JSON.stringify([-1, 0]);
})()"#;

const RESTORE: &str = r#"function (a) {
  const e = document.getElementsByTagName('*')[a[0]];
  if (!e) return JSON.stringify(null);
  const r = e.getBoundingClientRect();
  return JSON.stringify(Math.max(0, Math.round(r.top + window.scrollY + a[1] * r.height)));
}"#;

/// The top hint puts the marked source line a third of the way down the viewport.
const READY: &str = r#"function (a) {
  const d = document.documentElement, hit = document.querySelector('tr.hit');
  const ready = location.search === a.search && document.readyState === 'complete';
  const y = hit ? hit.getBoundingClientRect().top + window.scrollY - window.innerHeight / 3 : 0;
  return JSON.stringify([ready, d ? d.scrollHeight : 0, Math.max(0, Math.round(y))]);
}"#;

const IMAGES_PENDING: &str =
    "(() => JSON.stringify(Array.prototype.filter.call(document.images, (i) => !i.complete).length))()";

fn call(body: &str, args: &serde_json::Value) -> String {
    format!("({body})({args})")
}

/// The regular expression source for a query: the text itself when `regex` is set, else the text with its regex
/// syntax escaped; wrapped in Unicode-aware word boundaries when `word` is set. Empty text stays empty.
fn source(q: &FindQuery) -> String {
    if q.text.is_empty() {
        return String::new();
    }
    let mut src = String::new();
    if q.regex {
        src.push_str(&q.text);
    } else {
        for c in q.text.chars() {
            if r"\^$.|?*+()[]{}".contains(c) {
                src.push('\\');
            }
            src.push(c);
        }
    }
    if q.word {
        src = format!("(?<!{WORD_CHAR})(?:{src})(?!{WORD_CHAR})");
    }
    src
}

/// Mark every match (CSS Custom Highlight API) and make match `index` current: `[count, index, y]`; no match
/// `[0, 0, -1]`; an invalid regular expression `[-1, 0, -1]`. `index` may be negative or past the end; the reply
/// carries it normalised. `y` is the current match's top in document CSS px.
pub fn find(q: &FindQuery, index: i64) -> String {
    let flags = if q.case { "gu" } else { "gui" };
    call(FIND, &serde_json::json!({ "src": source(q), "flags": flags, "index": index }))
}

pub fn find_clear() -> String {
    FIND_CLEAR.to_string()
}

/// The `href` of the link under the viewport point, or `null`. A link within the page (`#...`) comes back as
/// written; any other is resolved to an absolute URL.
pub fn hit(x_css: f64, y_css: f64) -> String {
    call(HIT, &serde_json::json!({ "x": x_css, "y": y_css }))
}

/// `[element index, offset]` of the element at the top of the viewport, to keep the reading position: the index
/// among `document.getElementsByTagName('*')`, the offset a fraction of its height. `[-1, 0]` if none.
pub fn anchor() -> String {
    ANCHOR.to_string()
}

/// The scroll y that puts the element from `anchor()` back at the top, or `null` when it is gone. Anything that is
/// not an `anchor()` reply gives `null`.
pub fn restore(anchor_json: &str) -> String {
    match serde_json::from_str::<(i64, f64)>(anchor_json) {
        Ok((index, offset)) if index >= 0 && offset.is_finite() => call(RESTORE, &serde_json::json!([index, offset])),
        _ => "JSON.stringify(null)".to_string(),
    }
}

/// `[ready, scrollHeight, topHint]`: ready when the page URL carries `?peek=<marker>` and `readyState` is complete.
pub fn ready(marker: u64) -> String {
    call(READY, &serde_json::json!({ "search": format!("?peek={marker}") }))
}

/// Number of images not finished loading.
pub fn images_pending() -> String {
    IMAGES_PENDING.to_string()
}
