use crate::api::Api;
use anyhow::Result;
use std::{thread, time::Duration};

pub fn run(api: &Api) -> Result<()> {
    let job_id = api.trigger()?;
    println!("triggered job {job_id}, waiting...");
    loop {
        let st = api.job_status(&job_id)?;
        match st["status"].as_str().unwrap_or("") {
            "done" => {
                println!("done: report {}", st["report_date"].as_str().unwrap_or(""));
                return Ok(());
            }
            "failed" => {
                anyhow::bail!("job failed: {}", st["error"].as_str().unwrap_or(""));
            }
            _ => thread::sleep(Duration::from_secs(3)),
        }
    }
}
