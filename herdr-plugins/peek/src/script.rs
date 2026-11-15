//! Scripts peek runs in the page through `evaluateJavaScript` (page scripts are off). Each evaluates to a JSON
//! string. (Task 3)

#[derive(Clone, Debug, Default, PartialEq)]
pub struct FindQuery {
    pub text: String,
    pub case: bool,
    pub word: bool,
    pub regex: bool,
}

/// Mark every match (CSS Custom Highlight API) and make match `index` current: `[count, index, y]`; no match
/// `[0, 0, -1]`; an invalid regular expression `[-1, 0, -1]`.
pub fn find(_q: &FindQuery, _index: i64) -> String {
    String::new()
}

pub fn find_clear() -> String {
    String::new()
}

/// The `href` of the link under the viewport point, or `null`.
pub fn hit(_x_css: f64, _y_css: f64) -> String {
    String::new()
}

/// `[element index, offset]` of the element at the top of the viewport, to keep the reading position.
pub fn anchor() -> String {
    String::new()
}

/// The scroll y that puts the element from `anchor()` back at the top.
pub fn restore(_anchor_json: &str) -> String {
    String::new()
}

/// `[ready, scrollHeight, topHint]`: ready when the page URL carries `?peek=<marker>` and `readyState` is complete.
pub fn ready(_marker: u64) -> String {
    String::new()
}

/// Number of images not finished loading.
pub fn images_pending() -> String {
    String::new()
}
