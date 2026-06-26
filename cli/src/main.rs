mod api;
mod commands;
mod config;

use anyhow::Result;
use api::Api;
use clap::{Parser, Subcommand};
use commands::resolve_endpoint;
use config::Config;

/// pusher — AI daily-report pusher CLI.
///
/// Manage your account and portfolio, trigger the multi-agent analysis
/// pipeline, and read the daily reports it emails out. The auth token and
/// default endpoint are stored in ~/.pusher/config.toml.
#[derive(Parser)]
#[command(name = "pusher", version, about, long_about = None)]
struct Cli {
    /// Backend base URL (overrides the saved endpoint), e.g. https://host
    #[arg(long, global = true)]
    endpoint: Option<String>,
    #[command(subcommand)]
    cmd: Command,
}

#[derive(Subcommand)]
enum Command {
    /// Create an account and save the returned auth token
    Register {
        /// Email address to register
        #[arg(long)]
        email: String,
    },
    /// Log in with an existing account and save the auth token
    Login {
        /// Registered email address
        #[arg(long)]
        email: String,
    },
    /// Clear the saved auth token from ~/.pusher/config.toml
    Logout,
    /// Manage the holdings analyzed in your daily report
    Portfolio {
        #[command(subcommand)]
        action: PortfolioCmd,
    },
    /// Read the daily analysis reports
    Report {
        #[command(subcommand)]
        action: ReportCmd,
    },
    /// Run the report pipeline on demand
    Trigger {
        #[command(subcommand)]
        action: TriggerCmd,
    },
}

#[derive(Subcommand)]
enum PortfolioCmd {
    /// Add a stock holding (quantity/cost optional; weight is derived)
    AddStock {
        /// Ticker / code, e.g. 600519 or AAPL
        code: String,
        /// Market: cn, hk, or us
        #[arg(long, default_value = "cn")]
        market: String,
        /// Shares held (optional)
        #[arg(long)]
        quantity: Option<f64>,
        /// Average cost price per share (optional)
        #[arg(long)]
        cost: Option<f64>,
    },
    /// Add a fund holding (China funds; market is always cn)
    AddFund {
        /// Fund code, e.g. 012345
        code: String,
        /// Units held (optional)
        #[arg(long)]
        quantity: Option<f64>,
        /// Average cost per unit (optional)
        #[arg(long)]
        cost: Option<f64>,
    },
    /// Remove a holding by its id (see `portfolio list`)
    Remove {
        /// Holding id to remove
        id: i64,
    },
    /// List your holdings
    List,
}

#[derive(Subcommand)]
enum ReportCmd {
    /// Show today's report
    Today,
    /// Show the report for a given date (YYYY-MM-DD)
    Get {
        /// Report date, e.g. 2026-06-25
        date: String,
    },
    /// List the dates that have a report
    List,
}

#[derive(Subcommand)]
enum TriggerCmd {
    /// Start a report job and poll until it finishes
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
