//! The scripts peek runs in the page. There is no browser here, so the tests read what Rust puts into each
//! script: every script with arguments has the shape `(function (a) { ... })(<JSON>)`, and the JSON is where the
//! query, flags, coordinates and marker go. What the bodies do in a page was checked by hand in a WebKit view
//! with page scripts off (the spike renderer's `eval` command).
use peek::script::{anchor, find, find_clear, hit, images_pending, ready, restore, FindQuery};
use serde_json::{json, Value};

/// The JSON argument of a script `(function (a) { ... })(<JSON>)`.
fn args(script: &str) -> Value {
    let at = script.find("})(").unwrap_or_else(|| panic!("no argument in {script}"));
    let json = script[at + 3..].strip_suffix(')').unwrap();
    serde_json::from_str(json).unwrap_or_else(|e| panic!("{e}: {json}"))
}

fn q(text: &str, case: bool, word: bool, regex: bool) -> FindQuery {
    FindQuery { text: text.into(), case, word, regex }
}

/// Every script is one expression whose value is `JSON.stringify(...)`.
fn assert_replies_json(script: &str) {
    assert!(script.starts_with('(') && script.ends_with(')'), "{script}");
    assert!(script.contains("JSON.stringify("), "{script}");
}

#[test]
fn find_escapes_query() {
    let s = find(&q(r#"a.b"c\d(e)*'"#, false, false, false), 0);
    assert_replies_json(&s);
    // Regex syntax in the text is escaped; quotes and backslashes survive the trip into the script.
    assert_eq!(args(&s)["src"], json!(r#"a\.b"c\\d\(e\)\*'"#));
    assert!(s.contains("CSS.highlights") && s.contains("peek-find") && s.contains("peek-cur"));
    assert!(s.contains("createTreeWalker"));
}

#[test]
fn find_word_and_case_flags() {
    let plain = args(&find(&q("Foo", false, false, false), 2));
    assert_eq!(plain["src"], json!("Foo"));
    assert_eq!(plain["flags"], json!("gui"), "case off: ignore case");
    assert_eq!(plain["index"], json!(2));

    let cased = args(&find(&q("Foo", true, false, false), -1));
    assert_eq!(cased["flags"], json!("gu"));
    assert_eq!(cased["index"], json!(-1), "the script normalises the index against the count");

    let word = args(&find(&q("a+b", true, true, false), 0));
    assert_eq!(word["src"], json!(r"(?<![\p{L}\p{M}\p{N}_])(?:a\+b)(?![\p{L}\p{M}\p{N}_])"));
}

#[test]
fn find_regex_flag_and_bad_regex_reply() {
    let re = find(&q(r"fo+\s(bar|baz)", false, false, true), 0);
    assert_eq!(args(&re)["src"], json!(r"fo+\s(bar|baz)"), "a regular expression is passed as written");
    let word = args(&find(&q("a|b", false, true, true), 0));
    assert_eq!(word["src"], json!(r"(?<![\p{L}\p{M}\p{N}_])(?:a|b)(?![\p{L}\p{M}\p{N}_])"));

    let bad = find(&q("(", false, false, true), 0);
    assert_eq!(args(&bad)["src"], json!("("));
    // new RegExp runs inside try; an invalid one replies [-1, 0, -1].
    assert!(bad.contains("try") && bad.contains("new RegExp(a.src, a.flags)"));
    assert!(bad.contains("[-1, 0, -1]"));

    // An empty query clears the marks and replies "no match".
    let empty = find(&q("", false, true, true), 0);
    assert_eq!(args(&empty)["src"], json!(""));
    assert!(empty.contains("[0, 0, -1]"));
}

#[test]
fn find_clear_removes_marks() {
    let s = find_clear();
    assert_replies_json(&s);
    assert!(s.contains("CSS.highlights.delete('peek-find')") && s.contains("CSS.highlights.delete('peek-cur')"));
}

#[test]
fn hit_returns_closest_anchor_href() {
    let s = hit(12.5, 40.0);
    assert_replies_json(&s);
    assert_eq!(args(&s), json!({"x": 12.5, "y": 40.0}));
    assert!(s.contains("document.elementFromPoint(a.x, a.y)"));
    assert!(s.contains(".closest('a[href]')"));
    // An in-page link resolves against <base> (the document's folder), so its raw "#..." is returned instead.
    assert!(s.contains("getAttribute('href')") && s.contains("startsWith('#')"));
    assert!(s.contains("document.baseURI"));
}

#[test]
fn ready_checks_marker_and_ready_state() {
    let s = ready(7);
    assert_replies_json(&s);
    assert_eq!(args(&s), json!({"search": "?peek=7"}));
    assert_ne!(args(&ready(8)), args(&s));
    assert!(s.contains("location.search === a.search"));
    assert!(s.contains("document.readyState === 'complete'"));
    assert!(s.contains("scrollHeight"));
    assert!(s.contains("tr.hit"), "the marked source line gives the top hint");
}

#[test]
fn restore_reemits_anchor_numbers() {
    let s = restore("[12, 0.25]");
    assert_replies_json(&s);
    assert_eq!(args(&s), json!([12, 0.25]));
    // Anything that is not an anchor reply evaluates to null and never reaches the script as code.
    for bad in ["", "alert(1)", "[1]", r#"{"a":1}"#, "[1, 2, 3]", "[-1, 0]"] {
        assert_eq!(restore(bad), "JSON.stringify(null)", "{bad}");
    }
}

#[test]
fn anchor_and_images_pending_reply_json() {
    for s in [anchor(), images_pending()] {
        assert_replies_json(&s);
    }
    assert!(anchor().contains("elementFromPoint"));
    assert!(images_pending().contains("document.images") && images_pending().contains(".complete"));
}

#[test]
fn whole_word_and_regex_exclude_each_other_but_case_goes_with_both() {
    let mut q = FindQuery::default();
    q.toggle("word");
    q.toggle("regex");
    assert!(q.regex && !q.word);
    q.toggle("word");
    assert!(q.word && !q.regex);
    q.toggle("case");
    assert!(q.case && q.word);
    q.toggle("regex");
    assert!(q.case && q.regex && !q.word);
    q.toggle("regex");
    assert!(!q.regex && !q.word && q.case);
}
