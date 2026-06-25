pub mod auth;
pub mod portfolio;
pub mod report;
pub mod trigger;

use crate::config::Config;
use anyhow::{anyhow, Result};

pub fn resolve_endpoint(cli_endpoint: Option<String>, cfg: &Config) -> Result<String> {
    if let Some(e) = cli_endpoint {
        return Ok(e);
    }
    if let Ok(e) = std::env::var("PUSHER_ENDPOINT") {
        if !e.is_empty() {
            return Ok(e);
        }
    }
    if !cfg.server.endpoint.is_empty() {
        return Ok(cfg.server.endpoint.clone());
    }
    Err(anyhow!(
        "no endpoint configured; set PUSHER_ENDPOINT or use --endpoint"
    ))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::config::Config;

    #[test]
    fn prefers_cli_then_config() {
        let mut cfg = Config::default();
        cfg.server.endpoint = "https://cfg".into();
        assert_eq!(resolve_endpoint(Some("https://cli".into()), &cfg).unwrap(), "https://cli");
        std::env::remove_var("PUSHER_ENDPOINT");
        assert_eq!(resolve_endpoint(None, &cfg).unwrap(), "https://cfg");
    }

    #[test]
    fn errors_when_nothing_set() {
        std::env::remove_var("PUSHER_ENDPOINT");
        let cfg = Config::default();
        assert!(resolve_endpoint(None, &cfg).is_err());
    }
}
