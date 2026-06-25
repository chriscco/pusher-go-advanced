use serde::{Deserialize, Serialize};
use std::path::{Path, PathBuf};

#[derive(Serialize, Deserialize, Default, Clone, Debug)]
pub struct Server {
    pub endpoint: String,
}

#[derive(Serialize, Deserialize, Default, Clone, Debug)]
pub struct Auth {
    pub token: String,
    pub email: String,
}

#[derive(Serialize, Deserialize, Default, Clone, Debug)]
pub struct Config {
    #[serde(default)]
    pub server: Server,
    #[serde(default)]
    pub auth: Auth,
}

pub fn config_path() -> PathBuf {
    let mut p = dirs::home_dir().unwrap_or_else(|| PathBuf::from("."));
    p.push(".pusher");
    p.push("config.toml");
    p
}

impl Config {
    pub fn load() -> Config {
        Config::load_from(&config_path())
    }

    pub fn load_from(path: &Path) -> Config {
        match std::fs::read_to_string(path) {
            Ok(s) => toml::from_str(&s).unwrap_or_default(),
            Err(_) => Config::default(),
        }
    }

    pub fn save(&self) -> anyhow::Result<()> {
        self.save_to(&config_path())
    }

    pub fn save_to(&self, path: &Path) -> anyhow::Result<()> {
        if let Some(parent) = path.parent() {
            std::fs::create_dir_all(parent)?;
        }
        std::fs::write(path, toml::to_string_pretty(self)?)?;
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn load_missing_returns_default() {
        let p = std::path::Path::new("/nonexistent/pusher/config.toml");
        let c = Config::load_from(p);
        assert_eq!(c.auth.token, "");
    }

    #[test]
    fn save_and_load_roundtrip() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("config.toml");
        let mut c = Config::default();
        c.server.endpoint = "https://api.example.com".into();
        c.auth.token = "tok123".into();
        c.auth.email = "u@x.com".into();
        c.save_to(&path).unwrap();

        let loaded = Config::load_from(&path);
        assert_eq!(loaded.server.endpoint, "https://api.example.com");
        assert_eq!(loaded.auth.token, "tok123");
        assert_eq!(loaded.auth.email, "u@x.com");
    }
}
