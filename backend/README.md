## 启动后端

在项目根目录下：

```bash
cd /Users/abbybai/IdeaProjects/blitz_x402
uvicorn backend.main:app --reload
```

或者在 `backend` 目录下：

```bash
cd /Users/abbybai/IdeaProjects/blitz_x402/backend
uvicorn main:app --reload
```

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

### MCP / 前端 充值确认

- **方法**: POST  
- **路径**: `/api/v1/mcp/deposit-confirm`  
- **说明**: MCP tool 或前端在链上转账完成后调用，后端校验交易并在 MySQL 中增加余额。  
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

---

## Claude API 代理

### POST /api/v1/claude/messages

代理转发 Claude API 请求，支持流式和非流式响应。

**功能说明**：
1. 检查用户 MON 余额
2. 余额不足返回 402 状态码
3. 余额充足时转发到配置的后端服务
4. 支持 SSE 流式响应
5. 记录真实 token usage

**请求头**：
- `X-User-Address`（必填）：用户钱包地址
- `Content-Type`：application/json
- `anthropic-beta`（可选）：Claude API beta 特性

**请求体**（兼容 Claude API 格式）：
```json
{
  "model": "claude-3-5-sonnet-20241022",
  "max_tokens": 4096,
  "messages": [
    {
      "role": "user",
      "content": "Hello!"
    }
  ],
  "stream": false,
  "temperature": 1.0,
  "system": "You are a helpful assistant"
}
```

**成功响应**（200）：
- 非流式：返回完整 JSON 响应
- 流式：返回 SSE 事件流

**错误响应**：

余额不足（402）：
```json
{
  "error": "payment_required",
  "message": "Insufficient MON balance",
  "current_balance_mon": "0.5",
  "required_mon": "0.049152"
}
```

后端服务错误（503）：
```json
{
  "detail": "Backend service error: Connection timeout"
}
```

配置未设置（500）：
```json
{
  "detail": "Claude backend not configured"
}
```

**使用示例**：

非流式请求：
```bash
curl -X POST http://localhost:8000/api/v1/claude/messages \
  -H "Content-Type: application/json" \
  -H "X-User-Address: 0x1234..." \
  -d '{
    "model": "claude-3-5-sonnet-20241022",
    "max_tokens": 1024,
    "messages": [{"role": "user", "content": "你好"}]
  }'
```

流式请求：
```bash
curl -X POST http://localhost:8000/api/v1/claude/messages \
  -H "Content-Type: application/json" \
  -H "X-User-Address: 0x1234..." \
  -d '{
    "model": "claude-3-5-sonnet-20241022",
    "max_tokens": 1024,
    "messages": [{"role": "user", "content": "你好"}],
    "stream": true
  }'
```

**兑换比例说明**：
- 默认：1 MON = 100,000 tokens（可通过环境变量配置）
- 预估消耗：max_tokens × 1.2（安全系数）
- 扣费时机：请求前预扣，流结束后不退款

**环境变量配置**：

在 `.env` 文件中配置以下参数：

```bash
# 后端 Claude 代理服务地址（必填）
CLAUDE_BACKEND_URL=https://your-claude-relay.com/api/v1/messages

# Claude API Key（必填）
CLAUDE_API_KEY=sk-ant-xxxxx

# MON 和 Token 的兑换比例（1 MON = 多少 tokens）
MON_TO_TOKEN_RATE=100000

# 单次请求最大 tokens 限制
MAX_TOKENS_PER_REQUEST=8192

# Claude 请求超时时间（秒）
CLAUDE_REQUEST_TIMEOUT=300
```

---

## 部署和运行

参考现有的部署说明，确保：
1. MySQL 数据库已配置并运行
2. 环境变量已正确设置（特别是 Claude 相关配置）
3. user_balances 表已创建

启动服务：
```bash
python main.py
```

或使用 uvicorn：
```bash
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

