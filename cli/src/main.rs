mod api;
mod commands;
mod config;

use anyhow::Result;
use api::Api;
use clap::{Parser, Subcommand};
use commands::resolve_endpoint;
use config::Config;

#[derive(Parser)]
#[command(name = "pusher")]
struct Cli {
    #[arg(long, global = true)]
    endpoint: Option<String>,
    #[command(subcommand)]
    cmd: Command,
}

#[derive(Subcommand)]
enum Command {
    Register { #[arg(long)] email: String },
    Login { #[arg(long)] email: String },
    Logout,
    Portfolio { #[command(subcommand)] action: PortfolioCmd },
    Report { #[command(subcommand)] action: ReportCmd },
    Trigger { #[command(subcommand)] action: TriggerCmd },
}

#[derive(Subcommand)]
enum PortfolioCmd {
    AddStock { code: String,
        #[arg(long, default_value = "cn")] market: String,
        #[arg(long)] quantity: Option<f64>,
        #[arg(long)] cost: Option<f64> },
    AddFund { code: String,
        #[arg(long)] quantity: Option<f64>,
        #[arg(long)] cost: Option<f64> },
    Remove { id: i64 },
    List,
}

#[derive(Subcommand)]
enum ReportCmd {
    Today,
    Get { date: String },
    List,
}

#[derive(Subcommand)]
enum TriggerCmd {
    Run,
}

fn authed_api(cli_endpoint: Option<String>) -> Result<Api> {
    let cfg = Config::load();
    let endpoint = resolve_endpoint(cli_endpoint, &cfg)?;
    let token = if cfg.auth.token.is_empty() { None } else { Some(cfg.auth.token.clone()) };
    Ok(Api::new(endpoint, token))
}

fn main() -> Result<()> {
    let cli = Cli::parse();
    match cli.cmd {
        Command::Register { email } => {
            let endpoint = resolve_endpoint(cli.endpoint, &Config::load())?;
            commands::auth::register(endpoint, &email)
        }
        Command::Login { email } => {
            let endpoint = resolve_endpoint(cli.endpoint, &Config::load())?;
            commands::auth::login(endpoint, &email)
        }
        Command::Logout => commands::auth::logout(),
        Command::Portfolio { action } => {
            let api = authed_api(cli.endpoint)?;
            match action {
                PortfolioCmd::AddStock { code, market, quantity, cost } =>
                    commands::portfolio::add(&api, &code, "stock", &market, quantity, cost),
                PortfolioCmd::AddFund { code, quantity, cost } =>
                    commands::portfolio::add(&api, &code, "fund", "cn", quantity, cost),
                PortfolioCmd::Remove { id } => commands::portfolio::remove(&api, id),
                PortfolioCmd::List => commands::portfolio::list(&api),
            }
        }
        Command::Report { action } => {
            let api = authed_api(cli.endpoint)?;
            match action {
                ReportCmd::Today => commands::report::today(&api),
                ReportCmd::Get { date } => commands::report::get(&api, &date),
                ReportCmd::List => commands::report::list(&api),
            }
        }
        Command::Trigger { action } => {
            let api = authed_api(cli.endpoint)?;
            match action {
                TriggerCmd::Run => commands::trigger::run(&api),
            }
        }
    }
}
