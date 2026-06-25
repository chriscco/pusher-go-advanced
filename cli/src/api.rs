use anyhow::{anyhow, Result};
use serde::Deserialize;
use serde_json::{json, Value};

#[derive(Deserialize, Debug)]
pub struct Holding {
    pub id: i64,
    pub symbol: String,
    pub name: Option<String>,
    #[serde(rename = "type")]
    pub r#type: String,
    pub market: String,
    pub quantity: Option<f64>,
    pub cost_price: Option<f64>,
}

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

    fn get_json(&self, path: &str) -> Result<Value> {
        let mut req = self.client().get(self.url(path));
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

    fn delete(&self, path: &str) -> Result<()> {
        let mut req = self.client().delete(self.url(path));
        if let Some(t) = &self.token {
            req = req.bearer_auth(t);
        }
        let resp = req.send()?;
        if !resp.status().is_success() {
            return Err(anyhow!("HTTP {}", resp.status().as_u16()));
        }
        Ok(())
    }

    pub fn add_portfolio(&self, symbol: &str, type_: &str, market: &str,
                         quantity: Option<f64>, cost: Option<f64>) -> Result<i64> {
        let body = json!({
            "symbol": symbol, "type": type_, "market": market,
            "quantity": quantity, "cost_price": cost,
        });
        let v = self.post_json("/portfolio", body)?;
        v["id"].as_i64().ok_or_else(|| anyhow!("no id in response"))
    }

    pub fn list_portfolio(&self) -> Result<Vec<Holding>> {
        let v = self.get_json("/portfolio")?;
        Ok(serde_json::from_value(v)?)
    }

    pub fn remove_portfolio(&self, id: i64) -> Result<()> {
        self.delete(&format!("/portfolio/{}", id))
    }

    pub fn report(&self, path: &str) -> Result<Value> {
        self.get_json(path)
    }

    pub fn trigger(&self) -> Result<String> {
        let v = self.post_json("/trigger-report", json!({}))?;
        v["job_id"].as_str().map(String::from)
            .ok_or_else(|| anyhow!("no job_id"))
    }

    pub fn job_status(&self, id: &str) -> Result<Value> {
        self.get_json(&format!("/job/{}", id))
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

    #[test]
    fn add_portfolio_returns_id() {
        let server = MockServer::start();
        server.mock(|when, then| {
            when.method(POST).path("/portfolio");
            then.status(201).json_body(serde_json::json!({"id": 7}));
        });
        let api = Api::new(server.base_url(), Some("tok".into()));
        let id = api.add_portfolio("600519", "stock", "cn", Some(100.0), None).unwrap();
        assert_eq!(id, 7);
    }

    #[test]
    fn list_portfolio_parses_rows() {
        let server = MockServer::start();
        server.mock(|when, then| {
            when.method(GET).path("/portfolio");
            then.status(200).json_body(serde_json::json!([
                {"id": 1, "symbol": "600519", "name": "茅台", "type": "stock",
                 "market": "cn", "quantity": 100.0, "cost_price": null}
            ]));
        });
        let api = Api::new(server.base_url(), Some("tok".into()));
        let rows = api.list_portfolio().unwrap();
        assert_eq!(rows.len(), 1);
        assert_eq!(rows[0].symbol, "600519");
        assert_eq!(rows[0].quantity, Some(100.0));
    }

    #[test]
    fn trigger_and_poll() {
        let server = MockServer::start();
        server.mock(|when, then| {
            when.method(POST).path("/trigger-report");
            then.status(202).json_body(serde_json::json!({"job_id": "j1"}));
        });
        server.mock(|when, then| {
            when.method(GET).path("/job/j1");
            then.status(200).json_body(serde_json::json!({"status": "done", "report_date": "2026-06-25"}));
        });
        let api = Api::new(server.base_url(), Some("tok".into()));
        let jid = api.trigger().unwrap();
        assert_eq!(jid, "j1");
        let st = api.job_status(&jid).unwrap();
        assert_eq!(st["status"], "done");
    }
}
