use crate::api::Api;
use anyhow::Result;
use std::io::Write;
use std::{
    thread,
    time::{Duration, Instant},
};

const SPINNER_FRAMES: [char; 10] = ['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏'];

pub fn run(api: &Api) -> Result<()> {
    let job_id = api.trigger()?;
    println!("triggered job {job_id}");

    let start = Instant::now();
    let mut last_poll = Instant::now() - Duration::from_secs(2);
    let mut status = String::from("pending");
    let mut frame_idx = 0usize;

    loop {
        if last_poll.elapsed() >= Duration::from_secs(2) {
            last_poll = Instant::now();
            let st = api.job_status(&job_id)?;
            match st["status"].as_str().unwrap_or("") {
                "done" => {
                    print!("\r\x1b[K");
                    std::io::stdout().flush().ok();
                    println!(
                        "\u{2713} done: report {}",
                        st["report_date"].as_str().unwrap_or("")
                    );
                    return Ok(());
                }
                "failed" => {
                    print!("\r\x1b[K");
                    std::io::stdout().flush().ok();
                    anyhow::bail!("job failed: {}", st["error"].as_str().unwrap_or(""));
                }
                other if !other.is_empty() => {
                    status = other.to_string();
                }
                _ => {}
            }
        }

        let elapsed = start.elapsed().as_secs();
        let frame = SPINNER_FRAMES[frame_idx % SPINNER_FRAMES.len()];
        print!("\r{frame} {status}… {elapsed}s elapsed");
        std::io::stdout().flush().ok();
        frame_idx += 1;

        thread::sleep(Duration::from_millis(100));
    }
}
