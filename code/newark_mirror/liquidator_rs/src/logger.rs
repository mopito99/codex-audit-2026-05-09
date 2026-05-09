//! JSONL logger for unhealthy obligation events.

use anyhow::Result;
use serde::Serialize;
use std::fs::{File, OpenOptions};
use std::io::{BufWriter, Write};
use std::path::Path;

pub struct JsonlLogger {
    writer: BufWriter<File>,
}

impl JsonlLogger {
    pub fn open<P: AsRef<Path>>(path: P) -> Result<Self> {
        if let Some(parent) = path.as_ref().parent() {
            std::fs::create_dir_all(parent).ok();
        }
        let f = OpenOptions::new()
            .create(true)
            .append(true)
            .open(path)?;
        Ok(Self { writer: BufWriter::new(f) })
    }

    pub fn write<T: Serialize>(&mut self, event: &T) -> Result<()> {
        serde_json::to_writer(&mut self.writer, event)?;
        self.writer.write_all(b"\n")?;
        self.writer.flush()?;
        Ok(())
    }
}
