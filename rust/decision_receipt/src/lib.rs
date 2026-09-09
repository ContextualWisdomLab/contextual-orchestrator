//! One-clock initial-decision measurement; storage acknowledgement is caller-owned.
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use std::time::Instant;

/// Request-local monotonic state with no caller-supplied clock values.
#[pyclass]
pub struct DecisionReceipt {
    accepted_at: Instant,
    #[pyo3(get)]
    status: String,
    #[pyo3(get)]
    selection_elapsed_ns: Option<u64>,
    #[pyo3(get)]
    durable_ack_elapsed_ns: Option<u64>,
}

impl DecisionReceipt {
    fn elapsed_ns(&self) -> PyResult<u64> {
        self.accepted_at
            .elapsed()
            .as_nanos()
            .try_into()
            .map_err(|_| PyValueError::new_err("decision elapsed time overflow"))
    }
}

#[pymethods]
impl DecisionReceipt {
    /// Start at validated acceptance, before capacity admission.
    #[new]
    fn accepted() -> Self {
        Self {
            accepted_at: Instant::now(),
            status: "accepted".into(),
            selection_elapsed_ns: None,
            durable_ack_elapsed_ns: None,
        }
    }

    /// Record the initial selection without allowing later attempts to replace it.
    fn record_selection(&mut self) -> PyResult<()> {
        if self.status != "accepted" {
            return Err(PyValueError::new_err("selection requires accepted state"));
        }
        let elapsed = self.elapsed_ns()?;
        self.selection_elapsed_ns = Some(elapsed);
        self.status = "selected".into();
        Ok(())
    }

    /// Call only after a synchronous durable decision write returns successfully.
    fn record_durable_ack(&mut self) -> PyResult<()> {
        if self.status != "selected" {
            return Err(PyValueError::new_err(
                "acknowledgement requires selected state",
            ));
        }
        let elapsed = self.elapsed_ns()?;
        self.durable_ack_elapsed_ns = Some(elapsed);
        self.status = "acknowledged".into();
        Ok(())
    }

    /// Preserve a denominator-only terminal observation without a success duration.
    fn record_failure(&mut self, reason: &str) -> PyResult<()> {
        if !matches!(self.status.as_str(), "accepted" | "selected") {
            return Err(PyValueError::new_err("observation is already terminal"));
        }
        if !matches!(
            reason,
            "capacity_rejected"
                | "selection_failed"
                | "write_failed"
                | "cancelled"
                | "unfinished"
                | "store_unavailable"
        ) {
            return Err(PyValueError::new_err("unknown failure reason"));
        }
        self.status = reason.into();
        Ok(())
    }
}

/// Export the receipt separately from token counting.
#[pymodule]
fn _decision_receipt(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_class::<DecisionReceipt>()
}
