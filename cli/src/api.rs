use anyhow::{anyhow, Result};
use serde_json::{json, Value};

pub struct Api {
    pub endpoint: String,
    pub token: Option<String>,
}

impl Api {
    pub fn new(endpoint: impl Into<String>, token: Option<String>) -> Self {
        Api { endpoint: endpoint.into(), token }
    }

    fn url(&self, path: &str) -> String {
        format!("{}{}", self.endpoint.trim_end_matches('/'), path)
    }

    fn client(&self) -> reqwest::blocking::Client {
        reqwest::blocking::Client::new()
    }

    fn post_json(&self, path: &str, body: Value) -> Result<Value> {
        let mut req = self.client().post(self.url(path)).json(&body);
        if let Some(t) = &self.token {
            req = req.bearer_auth(t);
        }
        let resp = req.send()?;
        let status = resp.status();
        let text = resp.text().unwrap_or_default();
        if !status.is_success() {
            return Err(anyhow!("HTTP {}: {}", status.as_u16(), text));
        }
        Ok(serde_json::from_str(&text).unwrap_or(Value::Null))
    }

    pub fn register(&self, email: &str, password: &str) -> Result<String> {
        let v = self.post_json("/register", json!({"email": email, "password": password}))?;
        v["token"].as_str().map(String::from)
            .ok_or_else(|| anyhow!("no token in response"))
    }

    pub fn login(&self, email: &str, password: &str) -> Result<String> {
        let v = self.post_json("/login", json!({"email": email, "password": password}))?;
        v["token"].as_str().map(String::from)
            .ok_or_else(|| anyhow!("no token in response"))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use httpmock::prelude::*;

    #[test]
    fn login_returns_token() {
        let server = MockServer::start();
        let m = server.mock(|when, then| {
            when.method(POST).path("/login");
            then.status(200).json_body(serde_json::json!({"token": "abc"}));
        });
        let api = Api::new(server.base_url(), None);
        let tok = api.login("u@x.com", "pw").unwrap();
        m.assert();
        assert_eq!(tok, "abc");
    }

    #[test]
    fn login_failure_is_err() {
        let server = MockServer::start();
        server.mock(|when, then| {
            when.method(POST).path("/login");
            then.status(401).json_body(serde_json::json!({"detail": "bad"}));
        });
        let api = Api::new(server.base_url(), None);
        assert!(api.login("u@x.com", "wrong").is_err());
    }

    #[test]
    fn register_returns_token() {
        let server = MockServer::start();
        server.mock(|when, then| {
            when.method(POST).path("/register");
            then.status(201).json_body(serde_json::json!({"token": "newtok"}));
        });
        let api = Api::new(server.base_url(), None);
        assert_eq!(api.register("u@x.com", "pw").unwrap(), "newtok");
    }
}
