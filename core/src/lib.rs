use pyo3::prelude::*;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::collections::HashMap;
use thiserror::Error;

#[derive(Error, Debug)]
pub enum MergeError {
    #[error("JSON parse error: {0}")]
    JsonError(#[from] serde_json::Error),
}

#[derive(Debug, Serialize, Deserialize)]
pub struct MergeResult {
    /// The merged JSON value
    pub merged: Value,
    /// Keys that were auto-resolved (ours or theirs clearly won)
    pub auto_resolved_keys: Vec<String>,
    /// Keys where both sides changed differently — needs escalation
    pub conflict_keys: Vec<ConflictKey>,
    /// True if the merge is clean (no conflicts)
    pub is_clean: bool,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct ConflictKey {
    pub key: String,
    pub base_value: Option<Value>,
    pub ours_value: Option<Value>,
    pub theirs_value: Option<Value>,
}

/// Three-way merge for JSON objects.
///
/// Algorithm (for each key across base/ours/theirs):
///   1. Key only in ours  → take ours (new addition)
///   2. Key only in theirs → take theirs (new addition from other side)
///   3. Key in both, same value → take either (no conflict)
///   4. Key changed in ours, not in theirs → take ours
///   5. Key changed in theirs, not in ours → take theirs
///   6. Key changed in BOTH, differently → conflict_keys (escalate)
///   7. Key deleted in ours, not in theirs → delete (ours wins)
///   8. Key deleted in theirs, not in ours → delete (theirs wins)
///   9. Deleted in both → delete
///  10. Nested objects → recurse
pub fn three_way_merge_json(
    base: &Value,
    ours: &Value,
    theirs: &Value,
) -> Result<MergeResult, MergeError> {
    let base_obj = to_map(base);
    let ours_obj = to_map(ours);
    let theirs_obj = to_map(theirs);

    let all_keys: std::collections::HashSet<_> = base_obj
        .keys()
        .chain(ours_obj.keys())
        .chain(theirs_obj.keys())
        .cloned()
        .collect();

    let mut merged_map: HashMap<String, Value> = HashMap::new();
    let mut auto_resolved_keys: Vec<String> = Vec::new();
    let mut conflict_keys: Vec<ConflictKey> = Vec::new();

    for key in &all_keys {
        let base_val = base_obj.get(key);
        let ours_val = ours_obj.get(key);
        let theirs_val = theirs_obj.get(key);

        match (base_val, ours_val, theirs_val) {
            // Case 1: only in ours (new key we added)
            (None, Some(o), None) => {
                merged_map.insert(key.clone(), o.clone());
                auto_resolved_keys.push(key.clone());
            }
            // Case 2: only in theirs (new key they added)
            (None, None, Some(t)) => {
                merged_map.insert(key.clone(), t.clone());
                auto_resolved_keys.push(key.clone());
            }
            // Case 3: both added independently with same value
            (None, Some(o), Some(t)) if o == t => {
                merged_map.insert(key.clone(), o.clone());
                auto_resolved_keys.push(key.clone());
            }
            // Case 4+5+6: key exists in base, check what changed
            (Some(b), o_opt, t_opt) => {
                let ours_changed = o_opt.map_or(false, |o| o != b);
                let theirs_changed = t_opt.map_or(false, |t| t != b);

                match (ours_changed, theirs_changed) {
                    (false, false) => {
                        // Neither changed — keep base (or handle deletion)
                        if let Some(o) = o_opt {
                            merged_map.insert(key.clone(), o.clone());
                        }
                        // else: both deleted → omit key
                    }
                    (true, false) => {
                        // Only we changed it — take ours
                        if let Some(o) = o_opt {
                            merged_map.insert(key.clone(), o.clone());
                        }
                        auto_resolved_keys.push(key.clone());
                    }
                    (false, true) => {
                        // Only they changed it — take theirs
                        if let Some(t) = t_opt {
                            merged_map.insert(key.clone(), t.clone());
                        }
                        auto_resolved_keys.push(key.clone());
                    }
                    (true, true) => {
                        // Both changed — check if they ended up at same value
                        match (o_opt, t_opt) {
                            (Some(o), Some(t)) if o == t => {
                                merged_map.insert(key.clone(), o.clone());
                                auto_resolved_keys.push(key.clone());
                            }
                            // Nested objects: recurse
                            (Some(Value::Object(_)), Some(Value::Object(_))) => {
                                let nested = three_way_merge_json(
                                    b,
                                    o_opt.unwrap(),
                                    t_opt.unwrap(),
                                )?;
                                merged_map.insert(key.clone(), nested.merged);
                                // propagate nested conflicts with dotted key path
                                for ck in nested.conflict_keys {
                                    conflict_keys.push(ConflictKey {
                                        key: format!("{}.{}", key, ck.key),
                                        ..ck
                                    });
                                }
                                auto_resolved_keys.extend(
                                    nested.auto_resolved_keys
                                        .iter()
                                        .map(|k| format!("{}.{}", key, k)),
                                );
                            }
                            (o, t) => {
                                // Genuine unresolvable conflict — escalate
                                conflict_keys.push(ConflictKey {
                                    key: key.clone(),
                                    base_value: Some(b.clone()),
                                    ours_value: o.cloned(),
                                    theirs_value: t.cloned(),
                                });
                            }
                        }
                    }
                }
            }
            // Both added with different values (no base)
            (None, Some(o), Some(t)) => {
                conflict_keys.push(ConflictKey {
                    key: key.clone(),
                    base_value: None,
                    ours_value: Some(o.clone()),
                    theirs_value: Some(t.clone()),
                });
            }
            (None, None, None) => {}
        }
    }

    let is_clean = conflict_keys.is_empty();
    Ok(MergeResult {
        merged: Value::Object(merged_map.into_iter().collect()),
        auto_resolved_keys,
        conflict_keys,
        is_clean,
    })
}

fn to_map(v: &Value) -> HashMap<String, Value> {
    match v {
        Value::Object(m) => m.iter().map(|(k, v)| (k.clone(), v.clone())).collect(),
        _ => HashMap::new(),
    }
}

// ── PyO3 Python Bindings ──────────────────────────────────────────────────────

#[pyfunction]
fn py_three_way_merge(
    base_json: &str,
    ours_json: &str,
    theirs_json: &str,
) -> PyResult<String> {
    let base: Value = serde_json::from_str(base_json)
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))?;
    let ours: Value = serde_json::from_str(ours_json)
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))?;
    let theirs: Value = serde_json::from_str(theirs_json)
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))?;

    let result = three_way_merge_json(&base, &ours, &theirs)
        .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e.to_string()))?;

    serde_json::to_string(&result)
        .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e.to_string()))
}

#[pyfunction]
fn py_compute_diff(base_json: &str, changed_json: &str) -> PyResult<String> {
    let base: Value = serde_json::from_str(base_json)
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))?;
    let changed: Value = serde_json::from_str(changed_json)
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))?;

    let mut diffs: Vec<String> = Vec::new();
    if let (Value::Object(b), Value::Object(c)) = (&base, &changed) {
        for (k, cv) in c {
            match b.get(k) {
                None => diffs.push(format!("+ {}", k)),
                Some(bv) if bv != cv => diffs.push(format!("~ {}", k)),
                _ => {}
            }
        }
        for k in b.keys() {
            if !c.contains_key(k) {
                diffs.push(format!("- {}", k));
            }
        }
    }
    serde_json::to_string(&diffs)
        .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e.to_string()))
}

#[pymodule]
fn _core(_py: Python, m: &PyModule) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(py_three_way_merge, m)?)?;
    m.add_function(wrap_pyfunction!(py_compute_diff, m)?)?;
    Ok(())
}

// ── Unit Tests ────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn test_clean_merge_different_keys() {
        let base = json!({"x": 1, "y": 2});
        let ours = json!({"x": 99, "y": 2});
        let theirs = json!({"x": 1, "y": 77});
        let result = three_way_merge_json(&base, &ours, &theirs).unwrap();
        assert!(result.is_clean);
        assert_eq!(result.merged["x"], 99);
        assert_eq!(result.merged["y"], 77);
    }

    #[test]
    fn test_conflict_same_key_different_values() {
        let base = json!({"status": "idle"});
        let ours = json!({"status": "busy"});
        let theirs = json!({"status": "error"});
        let result = three_way_merge_json(&base, &ours, &theirs).unwrap();
        assert!(!result.is_clean);
        assert_eq!(result.conflict_keys.len(), 1);
        assert_eq!(result.conflict_keys[0].key, "status");
    }

    #[test]
    fn test_new_key_from_ours() {
        let base = json!({"x": 1});
        let ours = json!({"x": 1, "new_key": "hello"});
        let theirs = json!({"x": 1});
        let result = three_way_merge_json(&base, &ours, &theirs).unwrap();
        assert!(result.is_clean);
        assert_eq!(result.merged["new_key"], "hello");
    }
}
