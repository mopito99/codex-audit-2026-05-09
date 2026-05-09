//! Kamino protocol parsers and types.

pub mod accounts;
pub mod health;
pub mod ix;
pub mod reserve;

pub use accounts::{parse_obligation, ParsedObligation};
