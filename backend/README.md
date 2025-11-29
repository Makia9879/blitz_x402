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

