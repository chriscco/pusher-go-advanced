use crate::api::Api;
use crate::config::Config;
use anyhow::Result;

pub fn register(endpoint: String, email: &str) -> Result<()> {
    let pw = rpassword::prompt_password("Password: ")?;
    let token = Api::new(endpoint.clone(), None).register(email, &pw)?;
    save_session(endpoint, email, token)?;
    println!("registered and logged in as {email}");
    Ok(())
}

pub fn login(endpoint: String, email: &str) -> Result<()> {
    let pw = rpassword::prompt_password("Password: ")?;
    let token = Api::new(endpoint.clone(), None).login(email, &pw)?;
    save_session(endpoint, email, token)?;
    println!("logged in as {email}");
    Ok(())
}

pub fn logout() -> Result<()> {
    let mut cfg = Config::load();
    cfg.auth.token.clear();
    cfg.auth.email.clear();
    cfg.save()?;
    println!("logged out");
    Ok(())
}

fn save_session(endpoint: String, email: &str, token: String) -> Result<()> {
    let mut cfg = Config::load();
    cfg.server.endpoint = endpoint;
    cfg.auth.email = email.to_string();
    cfg.auth.token = token;
    cfg.save()
}
