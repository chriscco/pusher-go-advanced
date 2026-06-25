use crate::api::Api;
use anyhow::Result;

pub fn today(api: &Api) -> Result<()> {
    let v = api.report("/report/today")?;
    print_report(&v);
    Ok(())
}

pub fn get(api: &Api, date: &str) -> Result<()> {
    let v = api.report(&format!("/report/{date}"))?;
    print_report(&v);
    Ok(())
}

pub fn list(api: &Api) -> Result<()> {
    let v = api.report("/report/list")?;
    if let Some(dates) = v["dates"].as_array() {
        for d in dates {
            println!("{}", d.as_str().unwrap_or(""));
        }
    }
    Ok(())
}

fn print_report(v: &serde_json::Value) {
    println!("=== {} ===", v["report_date"].as_str().unwrap_or(""));
    println!("{}", v["content"].as_str().unwrap_or(""));
}
