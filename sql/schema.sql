CREATE TABLE IF NOT EXISTS users (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    email       VARCHAR(255) NOT NULL UNIQUE,
    password    VARCHAR(255) NOT NULL,
    model_key   VARCHAR(255) DEFAULT NULL,
    model_name  VARCHAR(64) DEFAULT NULL,
    model_endpoint VARCHAR(255) DEFAULT NULL,
    email_to    VARCHAR(255) NOT NULL,
    token       VARCHAR(128) NOT NULL,
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS portfolios (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    user_id     INT NOT NULL,
    symbol      VARCHAR(32) NOT NULL,
    name        VARCHAR(128),
    type        ENUM('stock', 'fund') NOT NULL,
    market      ENUM('cn', 'hk', 'us') NOT NULL DEFAULT 'cn',
    quantity    DECIMAL(16,4) DEFAULT NULL,
    cost_price  DECIMAL(10,4) DEFAULT NULL,
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id),
    INDEX idx_user (user_id)
);

CREATE TABLE IF NOT EXISTS fund_holdings (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    fund_code   VARCHAR(32) NOT NULL,
    stock_code  VARCHAR(32) NOT NULL,
    stock_name  VARCHAR(128),
    ratio       DECIMAL(5,2),
    quarter     VARCHAR(16) NOT NULL,
    updated_at  DATE NOT NULL,
    INDEX idx_fund (fund_code, quarter)
);

CREATE TABLE IF NOT EXISTS reports (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    user_id         INT NOT NULL,
    report_date     DATE NOT NULL,
    content         TEXT,
    news_summary    TEXT,
    stock_summary   TEXT,
    personal_analysis TEXT,
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id),
    INDEX idx_user_date (user_id, report_date)
);

CREATE TABLE IF NOT EXISTS rss_sources (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    name        VARCHAR(128),
    url         VARCHAR(512) NOT NULL,
    category    VARCHAR(64),
    lang        VARCHAR(8) DEFAULT 'zh',
    enabled     BOOLEAN DEFAULT TRUE,
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS jobs (
    id          VARCHAR(36) PRIMARY KEY,
    user_id     INT DEFAULT NULL,
    type        ENUM('pipeline', 'manual_report') NOT NULL,
    status      ENUM('pending', 'running', 'done', 'failed') NOT NULL DEFAULT 'pending',
    error       TEXT DEFAULT NULL,
    report_date DATE DEFAULT NULL,
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
    finished_at DATETIME DEFAULT NULL,
    INDEX idx_user (user_id),
    INDEX idx_status (status)
);
