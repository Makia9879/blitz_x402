## 启动后端

### 方式一：在项目根目录下启动

```bash
cd /Users/abbybai/IdeaProjects/blitz_x402
uvicorn backend.main:app --reload
```

### 方式二：在 backend 目录下启动

```bash
cd /Users/abbybai/IdeaProjects/blitz_x402/backend
uvicorn main:app --reload
```

### 方式三：使用 Python 直接运行

```bash
cd /Users/abbybai/IdeaProjects/blitz_x402/backend
python main.py
```

**注意**：
- 启动前确保已配置 `.env` 文件（参考 `env.example`）
- 确保 MySQL 数据库已启动（使用 `../database/start_mysql.sh` 或 docker compose）
- 默认端口：`8000`
- 访问 API 文档：`http://localhost:8000/docs`

## Python API 文档

所有接口基于 FastAPI，默认前缀为 `http://localhost:8000`。

### 健康检查

- **方法**: GET  
- **路径**: `/health`  
- **说明**: 检查链路和数据库是否可用。  
- **响应示例**:

```json
{
  "status": "healthy",
  "chain_id": 1337,
  "latest_block": 123456,
  "db_ok": true
}
```

### 获取 x402 报价

- **方法**: POST  
- **路径**: `/api/v1/x402/quote`  
- **说明**: 返回使用 x402 支付所需的 MON 金额（wei）和中转站钱包地址。  
- **请求体**:

```json
{
  "user_address": "0x用户地址",
  "amount": "1.0",
  "client_type": "mcp"
}
```

- **响应体**:

```json
{
  "price_wei": "1000000000000000000",
  "chain_id": 1337,
  "token": "MON",
  "pay_to": "0xTransitWallet",
  "description": "Recharge MON balance via x402"
}
```

### MCP 充值（通过 x402，不使用 thirdweb）

- **方法**: POST  
- **路径**: `/api/v1/mcp/recharge`  
- **说明**: MCP tool 调用此接口进行充值。Python 后端直接实现 x402 协议，支持三种使用方式：
  1. **服务账户自动代付模式**（推荐）：如果后端配置了 `PRIVATE_KEY`，用户只需调用接口，后端自动使用服务账户代付并完成充值（一步完成，用户无需提供私钥）
  2. **用户私钥自动支付模式**：提供 `private_key`，后端自动完成链上支付并确认充值（一步完成）
  3. **手动支付模式**：第一次调用返回 402 支付要求，客户端完成链上支付后再次调用并提供 `tx_hash`
  4. **直接确认模式**：直接提供 `tx_hash`，后端验证交易并更新余额
  
- **使用流程**:

  **方式一：服务账户自动代付（推荐，一步完成，用户无需提供私钥）**
  1. 后端在 `.env` 中配置 `PRIVATE_KEY`（服务账户私钥）
  2. 用户调用接口，不提供 `tx_hash` 和 `private_key`
  3. 后端自动使用服务账户代付、等待确认、验证交易、更新用户余额
  4. 返回充值结果
  
  **注意**：服务账户需要有足够的 MON 余额用于代付

  **方式二：用户私钥自动支付（一步完成）**
  1. 调用接口时提供 `private_key`（用户私钥）
  2. 后端自动完成链上支付、等待确认、验证交易、更新余额
  3. 返回充值结果

  **方式三：手动支付（两步流程）**
  1. **第一次调用（获取支付要求）**：不提供 `tx_hash` 和 `private_key`，且后端未配置 `PRIVATE_KEY`，接口返回 `402 Payment Required`
  2. **客户端完成链上支付**：从用户钱包向 `pay_to` 地址转账指定金额的 MON
  3. **第二次调用（确认充值）**：提供 `tx_hash`，后端验证交易并更新余额

- **请求字段说明**:
  - `user_address`: 用户钱包地址（可选，有默认值）
  - `amount`: 充值金额（人类可读，如 "1.0" 表示 1 MON）
  - `tx_hash`: 链上交易哈希（手动支付模式时提供）
  - `private_key`: 用户私钥（可选，如果提供则使用用户私钥自动支付；如果不提供且后端配置了 PRIVATE_KEY，则使用服务账户自动代付）

- **方式一：服务账户自动代付（推荐，用户无需提供私钥）**

**请求**（只需提供金额和用户地址）：

```json
{
  "amount": "1.0",
  "user_address": "0x你的钱包地址"
}
```

**成功响应**:

```json
{
  "success": true,
  "message": "Recharge successful via x402 (service account auto payment)",
  "tx_hash": "0x...",
  "new_balance": "1000000000000000000"
}
```

**curl 示例**:

```bash
curl -X POST http://localhost:8000/api/v1/mcp/recharge \
  -H "Content-Type: application/json" \
  -d '{
    "amount": "1.0",
    "user_address": "0x你的钱包地址"
  }'
```

**后端配置**（在 `backend/.env` 中）：

```bash
PRIVATE_KEY=0x服务账户的私钥  # 服务账户需要有足够的 MON 余额
```

- **方式二：用户私钥自动支付（一步完成）**

```json
{
  "amount": "1.0",
  "user_address": "0x你的钱包地址",
  "private_key": "0x你的私钥"
}
```

**成功响应**:

```json
{
  "success": true,
  "message": "Recharge successful via x402 (user auto payment)",
  "tx_hash": "0x...",
  "new_balance": "1000000000000000000"
}
```

**curl 示例**:

```bash
curl -X POST http://localhost:8000/api/v1/mcp/recharge \
  -H "Content-Type: application/json" \
  -d '{
    "amount": "1.0",
    "user_address": "0x你的钱包地址",
    "private_key": "0x你的私钥"
  }'
```

- **方式三：手动支付（两步流程）**

**第一步：获取支付要求**

```json
{
  "amount": "1.0"
}
```

**响应（402 状态码）**:

```json
{
  "payment_required": true,
  "amount": "1.0",
  "amount_wei": "1000000000000000000",
  "chain_id": 10143,
  "token": "MON",
  "pay_to": "0x中转站钱包地址",
  "user_address": "0x你的钱包地址",
  "description": "Please send MON to the transit wallet and provide tx_hash",
  "instructions": "Send MON transaction from your wallet to TRANSIT_WALLET, then call this endpoint again with tx_hash. Or provide private_key to auto-complete payment."
}
```

**第二步：完成支付后，提供 tx_hash**

```json
{
  "amount": "1.0",
  "user_address": "0x你的钱包地址",
  "tx_hash": "0x链上交易哈希"
}
```

**成功响应**:

```json
{
  "success": true,
  "message": "Recharge successful via x402",
  "tx_hash": "0x...",
  "new_balance": "1000000000000000000"
}
```

**curl 示例**:

```bash
# 第一步：获取支付要求
curl -X POST http://localhost:8000/api/v1/mcp/recharge \
  -H "Content-Type: application/json" \
  -d '{
    "amount": "1.0"
  }'

# 第二步：完成支付后，提供 tx_hash
curl -X POST http://localhost:8000/api/v1/mcp/recharge \
  -H "Content-Type: application/json" \
  -d '{
    "amount": "1.0",
    "user_address": "0x你的钱包地址",
    "tx_hash": "0x你的交易哈希"
  }'
```

- **方式四：直接确认（已完成的交易）**

```json
{
  "amount": "1.0",
  "user_address": "0x你的钱包地址",
  "tx_hash": "0x已完成的交易哈希"
}
```

### MCP / 前端 充值确认（直接提供 tx_hash）

- **方法**: POST  
- **路径**: `/api/v1/mcp/deposit-confirm`  
- **说明**: MCP tool 或前端在链上转账完成后调用，后端校验交易并在 MySQL 中增加余额。适用于已经完成链上转账的场景。  
- **请求体**:

```json
{
  "user_address": "0x用户地址",
  "amount_wei": "1000000000000000000",
  "tx_hash": "0x链上交易哈希",
  "client_type": "mcp"
}
```

- **成功响应**:

```json
{
  "success": true,
  "message": "Deposit successful",
  "tx_hash": "0x...",
  "new_balance": "1000000000000000000"
}
```

### 内部充值（x402 网关调用）

- **方法**: POST  
- **路径**: `/internal/recharge`  
- **说明**: 仅供 Node/TS x402 网关调用。假定支付已由 thirdweb 完成，这里只更新 MySQL 余额。  
- **请求体**:

```json
{
  "user_address": "0x用户地址",
  "amount": "1.0",
  "client_type": "x402-gateway"
}
```

- **成功响应**:

```json
{
  "success": true
}
```

### 查询余额（POST）

- **方法**: POST  
- **路径**: `/api/v1/balance`  
- **说明**: 从 MySQL 查询用户在中转站中的充值余额。  
- **请求体**:

```json
{
  "user_address": "0x用户地址"
}
```

- **响应体**:

```json
{
  "user_address": "0x用户地址",
  "balance": "1000000000000000000",
  "balance_mon": "1.0"
}
```

### 查询余额（GET）

- **方法**: GET  
- **路径**: `/api/v1/balance/{user_address}`  
- **说明**: 与 POST `/api/v1/balance` 相同，只是地址在路径中。  
- **示例**:

```bash
curl http://localhost:8000/api/v1/balance/0x用户地址
```

## 自动充值脚本

为了方便测试和自动化充值流程，提供了 `auto_recharge.py` 脚本，可以一键完成整个 x402 充值流程：

1. 调用充值接口获取 402 支付要求
2. 自动完成链上 MON 转账
3. 再次调用接口确认充值并更新余额

### 使用方法

**基本用法**（使用环境变量中的 `PRIVATE_KEY`）：

```bash
cd backend
python auto_recharge.py --amount 1.0
```

**指定用户地址**：

```bash
python auto_recharge.py --amount 1.0 --user-address 0x你的钱包地址
```

**使用自定义私钥**：

```bash
python auto_recharge.py --amount 1.0 --private-key 0x你的私钥
```

**不等待交易确认**（快速模式）：

```bash
python auto_recharge.py --amount 1.0 --no-wait
```

**自定义后端 URL**：

```bash
python auto_recharge.py --amount 1.0 --backend-url http://localhost:8000
```

### 环境变量配置

确保在 `backend/.env` 中配置了以下变量：

```bash
PRIVATE_KEY=0x你的私钥
TRANSIT_WALLET=0x中转站钱包地址
RPC_URL=https://testnet-rpc.monad.xyz
CHAIN_ID=10143
BACKEND_URL=http://localhost:8000  # 可选，默认 localhost:8000
```

### 示例输出

```
======================================================================
🚀 x402 Auto Recharge
======================================================================
Amount: 1.0 MON
User Address: 0x...
Backend URL: http://localhost:8000
RPC URL: https://testnet-rpc.monad.xyz
Chain ID: 10143
======================================================================

[Step 1] Requesting payment requirement from http://localhost:8000/api/v1/mcp/recharge...
[Step 1] ✅ Received 402 Payment Required
[Step 1] Payment details:
  - Amount: 1.0 MON (1000000000000000000 wei)
  - Pay to: 0x...
  - Chain ID: 10143
  - Token: MON

[Step 2] Preparing payment...
  - From: 0x...
  - To: 0x...
  - Amount: 1.0 MON (1000000000000000000 wei)
  - Balance: 10.0 MON (10000000000000000000 wei)
[Step 2] Sending transaction...
[Step 2] ✅ Transaction sent: 0x...
[Step 2] Waiting for confirmation...
[Step 2] ✅ Transaction confirmed in block 12345

[Step 3] Confirming recharge...
[Step 3] ✅ Recharge confirmed successfully!
[Step 3] New balance: 1000000000000000000 wei (1.0 MON)

======================================================================
✅ Recharge Completed Successfully!
======================================================================
Transaction Hash: 0x...
New Balance: 1000000000000000000 wei (1.0 MON)
Message: Recharge successful via x402
======================================================================
```

### 自动化处理 402 响应

当你调用 `/api/v1/mcp/recharge` 收到 402 响应后，可以使用以下方式自动化完成充值：

#### 方式一：使用 `auto_recharge.py`（推荐）

这是最简单的方式，一键完成整个流程：

```bash
cd backend
python auto_recharge.py --amount 1.0
```

#### 方式二：使用 `example_auto_recharge.py`（学习示例）

这个脚本展示了如何解析 402 响应并自动完成支付：

```bash
cd backend
python example_auto_recharge.py 1.0
```

或者指定用户地址：

```bash
python example_auto_recharge.py 1.0 0x你的钱包地址
```

#### 方式三：手动两步操作

**步骤 1：使用 `send_payment.py` 完成链上支付**

```bash
python send_payment.py --amount 1.0 --to 0xb1fD9C228aeF736B25140049f774b3b99456c10D
```

这会返回 `tx_hash`，例如：`0xabc123...`

**步骤 2：使用 curl 确认充值**

```bash
curl -X POST http://localhost:8000/api/v1/mcp/recharge \
  -H "Content-Type: application/json" \
  -d '{
    "user_address": "0x你的钱包地址",
    "amount": "1.0",
    "tx_hash": "0xabc123..."
  }'
```

### 手动支付脚本

如果只需要完成链上支付部分（不自动确认充值），可以使用 `send_payment.py`：

```bash
python send_payment.py --amount 1.0 --to 0x中转站钱包地址
```

