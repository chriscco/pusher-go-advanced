# 部署手册

## 一键部署（推荐）

先建好数据库（见下方第 1 节），export 好机密，然后：

```bash
export MYSQL_HOST=... MYSQL_USER=... MYSQL_PASSWORD=... MYSQL_DATABASE=pusher
export TENCENT_SECRET_ID=... TENCENT_SECRET_KEY=...
export DEEPSEEK_API_KEY=...                 # 其余可选项见脚本顶部
bash deploy/deploy.sh
```

`deploy.sh` 会：构建带依赖的函数包（Docker 内装，与运行时对齐）→ 注入环境变量与
`TIMER_SECRET`（未提供则自动生成）→ `serverless deploy` 出函数 + API 网关 + 每日
08:00 Timer。**依赖直接打进函数包，无需手动建层上传 layer.zip。**

> 偏好「依赖层」方案的话，跳过本脚本，按下面的分步手册（第 2 节用 `build_layer.sh` +
> 控制台建层 + `serverless.yml`）操作。

### 数据库走内网（如 TDSQL-C 只暴露内网地址）

`MYSQL_HOST` 填内网 IP/域名，并把函数绑定到数据库所在的 **VPC + 子网**：

```bash
export VPC_ID=vpc-xxxx SUBNET_ID=subnet-xxxx   # 见 TDSQL-C 实例「网络信息」
bash deploy/deploy.sh
```

注意两点：

- **公网出口**：函数绑定 VPC 后默认无公网出口，需为函数另开「公网访问」或在 VPC
  挂 NAT 网关，否则 DeepSeek / yfinance / akshare / SMTP / RSS 等外网调用会超时。
- **建表**：本地连不到内网库，用腾讯云 **DMC 控制台** 的 SQL 窗口执行 `sql/schema.sql`，
  或临时为 TDSQL-C 开启外网地址执行完再关闭。
- `vpcConfig` 字段名以你所用 serverless `scf` 组件版本为准，若部署报字段无法识别，
  改用 `vpc`。

---

## 0. 准备（分步手册）
- 腾讯云账号，开通 SCF / API 网关 / CDB(MySQL) / COS。
- 本机安装 Docker（构建依赖层）与 Serverless Framework：`npm i -g serverless`。
- 配置腾讯云凭证：`export TENCENT_SECRET_ID=... TENCENT_SECRET_KEY=...`。

## 1. 数据库
1. 创建 CDB MySQL（最小 1核1G），库名 `pusher`。
2. 应用建表脚本：
   ```bash
   mysql -h <host> -u <user> -p pusher < sql/schema.sql
   ```
3. 安全组只放行 SCF 出口网段访问 3306。
4. （可选）插入初始 RSS 源：
   ```sql
   INSERT INTO rss_sources (name, url, category) VALUES
     ('华尔街见闻', 'https://dedicated-feed-url', 'business');
   ```

## 2. 依赖层
```bash
bash deploy/build_layer.sh           # 产出 deploy/layer.zip
```
在 SCF 控制台 → 层管理 → 新建层，运行时 Python3.10，上传 `layer.zip`（>50MB 经 COS）。记下层名 `pusher-deps` 与版本号，回填 `serverless.yml` 的 `layers`。

## 3. 环境变量
导出全部机密（见 spec §7.2 + `TIMER_SECRET`）：
```bash
export MYSQL_HOST=... MYSQL_USER=... MYSQL_PASSWORD=... MYSQL_DATABASE=pusher
export MYSQL_PORT=3306
export DEEPSEEK_API_KEY=... DEEPSEEK_MODEL=deepseek-chat PLANNER_MODEL=deepseek-r1
export EMAIL_SMTP_HOST=smtp.gmail.com EMAIL_SMTP_PORT=587 EMAIL_FROM=... EMAIL_PASSWORD=...
export TIMER_SECRET=$(openssl rand -hex 16)
```
把 `serverless.yml` 里 timer 的 `argument` 改为与 `TIMER_SECRET` 相同的值。

## 4. 部署
```bash
cd deploy && serverless deploy
```
输出里记下 API 网关 HTTPS 地址。

## 5. 烟测
```bash
curl https://<apigw-host>/health        # 期望 {"status":"ok"}
```
用 CLI 走通注册→加持仓→触发：
```bash
export PUSHER_ENDPOINT=https://<apigw-host>
pusher register --email you@x.com
pusher portfolio add-stock 600519 --quantity 100
pusher trigger run                       # 触发并轮询至 done
pusher report today
```

## 6. 验证定时
等次日 8:00，或在控制台手动触发 timer，确认收到日报邮件、`reports` 表有当日记录、`jobs` 表对应 job 为 done。
