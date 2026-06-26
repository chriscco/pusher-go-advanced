use crate::api::Api;
use anyhow::Result;

pub fn add(api: &Api, symbol: &str, type_: &str, market: &str,
           quantity: Option<f64>, cost: Option<f64>) -> Result<()> {
    let id = api.add_portfolio(symbol, type_, market, quantity, cost)?;
    println!("added portfolio #{id}");
    Ok(())
}

pub fn remove(api: &Api, id: i64) -> Result<()> {
    api.remove_portfolio(id)?;
    println!("removed #{id}");
    Ok(())
}

pub fn list(api: &Api) -> Result<()> {
    for h in api.list_portfolio()? {
        let q = h.quantity.map(|v| v.to_string()).unwrap_or_else(|| "-".into());
        let name = h.name.as_deref().map(|n| format!(" {n}")).unwrap_or_default();
        let cost = h.cost_price.map(|v| format!(" cost={v}")).unwrap_or_default();
        println!("#{} {}{} [{}/{}] qty={}{}", h.id, h.symbol, name, h.r#type, h.market, q, cost);
    }
    Ok(())
}
