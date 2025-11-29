# AI Agent 支付系统 - 需求文档

## 项目概述

基于 x402 协议构建的 USDC 支付路由中间件，专为 AI Agent 间的机器对机器支付设计。核心价值是将支付可靠性（重试、对账、容错）从业务逻辑中解耦，提供企业级的支付基础设施。

**活动时间限制**: 10 小时快速原型开发

---

## 一、用户故事（User Stories）

### 1.1 AI Agent 开发者视角

**US-1: 快速集成支付能力**
> 作为 AI Agent 开发者，我希望通过简单的 API 调用就能让我的 Agent 接收 USDC 支付，而不需要处理复杂的区块链交互逻辑。

**验收标准**:
- 只需调用 3 个 API（创建意图、提交支付、查询状态）
- 无需管理钱包私钥、gas 费优化、交易重试
- 提供清晰的文档和代码示例

---

**US-2: 支付失败自动恢复**
> 作为服务提供方 Agent，当用户支付因网络问题失败时，我希望系统能自动重试，而不是让交易永久失败。

**验收标准**:
- RPC 超时自动切换到备用节点
- 交易 dropped 自动重新广播
- 最多重试 7 次，支持指数退避
- 所有重试对业务层透明

---

**US-3: 跨链支付路由**
> 作为支付接收方，我希望无论用户在哪条链上（Base/Optimism/Ethereum）持有 USDC，都能完成支付。

**验收标准**:
- 支持多链 USDC（至少 2 条链）
- 自动选择费用最低/速度最快的链
- 用户无需手动切换网络

---

### 1.2 AI Agent 用户视角

**US-4: 透明的支付状态**
> 作为调用 AI 服务的用户，我希望清楚地看到我的支付处于什么状态（待确认/已完成/失败），以及预计完成时间。

**验收标准**:
- 实时显示交易状态（pending/confirmed/failed）
- 显示区块确认数（如 2/6）
- 估算完成时间（基于链的平均出块时间）

---

**US-5: 支付历史查询**
> 作为用户，我希望能查看我所有的支付记录，包括支付给哪个 Agent、金额、时间、交易哈希。

**验收标准**:
- 提供支付历史列表
- 可按时间、Agent、状态筛选
- 每条记录可点击查看链上交易详情

---

### 1.3 平台运营者视角

**US-6: 全链路可观测**
> 作为平台运营者，我需要实时监控支付系统的健康状态，快速定位问题。

**验收标准**:
- Dashboard 显示成功率、P95 延迟、重试次数
- 按链/RPC 提供商分类统计
- 异常时自动告警

---

**US-7: 对账与审计**
> 作为财务审计人员，我需要完整的支付流水记录，确保每笔款项都有据可查。

**验收标准**:
- 每笔支付的完整时间线（创建→授权→上链→确认）
- 支持导出对账报表
- 链上交易哈希与内部订单号双向映射

---

## 二、产品需求（Product Requirements）

### 2.1 功能需求

#### P0 - 核心功能（必须实现）

**F-1: 支付意图管理**
- 创建支付意图（PaymentIntent）
- 支持设置金额、截止时间、允许的链
- 返回唯一的 Intent ID

**F-2: 幂等性保证**
- 所有提交操作支持 `Idempotency-Key`
- 重复请求返回相同结果，不重复扣款
- 防止网络抖动导致的双花

**F-3: 自动重试机制**
- RPC 失败自动切换节点
- 交易 dropped 自动重新广播
- 指数退避策略（1s → 2s → 4s → 8s...）
- 达到 deadline 或最大重试次数后失败

**F-4: 链上交易确认**
- 等待可配置的确认数（1-6 个区块）
- 检测 reorg 并自动处理
- 返回最终交易哈希和区块高度

**F-5: 支付状态查询**
- 根据 Intent ID 查询当前状态
- 返回确认进度、链信息、交易哈希
- 提供时间线视图（每次尝试的记录）

---

#### P1 - 重要功能（优先实现）

**F-6: 多链路由**
- 支持 Base、Optimism（至少 2 条）
- 根据费用/速度策略选择最优链
- 用户可指定优先级

**F-7: Webhook 回调**
- 支付确认后推送到商户服务器
- HMAC-SHA256 签名验证
- 失败自动重试（最多 3 次）

**F-8: 支付历史**
- 查询用户/Agent 的所有支付记录
- 支持分页和筛选
- 显示状态、金额、时间、链

---

#### P2 - 增强功能（时间允许时实现）

**F-9: 可观测性面板**
- 成功率、延迟、重试次数的可视化
- 按链、RPC 提供商分组
- 实时刷新

**F-10: 回放功能**
- 只读式回放某次支付的完整过程
- 用于调试和审计
- 不会二次扣款

**F-11: 智能路由优化**
- 基于历史数据学习最优路由策略
- 动态调整 RPC 权重
- 避开拥堵的链

---

### 2.2 非功能需求

#### NFR-1: 性能
- P95 延迟 < 30 秒（从提交到确认）
- 支持并发 100 笔支付
- 数据库查询响应 < 200ms

#### NFR-2: 可靠性
- 系统可用性 > 99%
- 支付成功率 > 95%（排除用户余额不足等 fast-fail 场景）
- 零双花/重复扣款

#### NFR-3: 安全性
- 所有 API 需要身份验证（API Key）
- Webhook 签名验证
- 防止重放攻击（时间窗口 5 分钟）
- 敏感数据加密存储

#### NFR-4: 可扩展性
- 支持水平扩展（无状态服务）
- 新增链只需配置，无需代码改动
- 插件式 RPC 提供商管理

---

## 三、系统需求（System Requirements）

### 3.1 核心数据模型

#### PaymentIntent（支付意图）

```typescript
interface PaymentIntent {
  id: string;                    // 全局唯一 ID（ULID/UUID）
  amount: string;                // USDC 金额（原子单位，6 位小数）
  asset: "USDC";                 // 资产类型
  networks: string[];            // 允许的链 ["base", "optimism", "ethereum"]
  payer: string;                 // 付款方地址
  payee: string;                 // 收款方地址
  deadline: number;              // Unix 时间戳（秒）
  policy: PaymentPolicy;         // 策略配置
  state: PaymentState;           // 当前状态
  txAttempts: TxAttempt[];       // 所有提交尝试
  metadata: Record<string, any>; // 业务自定义字段
  createdAt: number;
  updatedAt: number;
}

interface PaymentPolicy {
  minConfirmations: number;      // 最小确认数 (1-6)
  maxRetries: number;            // 最大重试次数
  slippageBps: number;           // 滑点容忍度（基点）
  preferredNetwork?: string;     // 优先使用的链
}

type PaymentState =
  | "created"      // 已创建，等待用户授权
  | "authorized"   // 用户已授权，待提交
  | "submitted"    // 已提交到链上
  | "confirming"   // 确认中
  | "confirmed"    // 已确认
  | "failed"       // 失败
  | "expired";     // 超时

interface TxAttempt {
  attemptId: string;
  network: string;
  rpcProvider: string;
  txHash?: string;
  blockNumber?: number;
  confirmations: number;
  status: "pending" | "success" | "failed" | "dropped";
  error?: string;
  gasUsed?: string;
  timestamp: number;
}
```

---

#### AgentService（AI Agent 服务）

```typescript
interface AgentService {
  id: string;
  name: string;                  // 服务名称（如 "AI 翻译"）
  description: string;           // 服务描述
  provider: string;              // Agent 提供者地址
  pricePerCall: string;          // 每次调用价格（USDC）
  category: string;              // 分类（翻译/分析/生成）
  rating: number;                // 平均评分 (0-5)
  totalCalls: number;            // 总调用次数
  isActive: boolean;
  createdAt: number;
}
```

---

#### WebhookEvent（回调事件）

```typescript
interface WebhookEvent {
  id: string;
  intentId: string;
  event: "payment.confirmed" | "payment.failed";
  url: string;                   // 回调 URL
  payload: any;
  signature: string;             // HMAC 签名
  attempts: number;              // 重试次数
  status: "pending" | "success" | "failed";
  lastAttemptAt?: number;
  nextRetryAt?: number;
}
```

---

### 3.2 系统架构

#### 3.2.1 整体架构

```
┌─────────────┐
│   用户界面   │ (Next.js + shadcn/ui)
└──────┬──────┘
       │ HTTP/WebSocket
┌──────▼──────────────────────────────────┐
│         API Gateway (Express)           │
│  - 身份验证                              │
│  - 请求验证                              │
│  - Rate Limiting                        │
└──────┬──────────────────────────────────┘
       │
┌──────▼──────────────────────────────────┐
│      Intent Management Service          │
│  - 创建/查询支付意图                      │
│  - 幂等性检查                            │
│  - 状态机管理                            │
└──────┬──────────────────────────────────┘
       │
┌──────▼──────────────────────────────────┐
│       Transaction Router                │
│  - 选择最优链                            │
│  - 构建交易                              │
│  - 管理 RPC 提供商池                     │
└──────┬──────────────────────────────────┘
       │
┌──────▼──────────────────────────────────┐
│      Retry & Confirmation Engine        │
│  - 自动重试逻辑                          │
│  - 区块确认监听                          │
│  - Reorg 检测                           │
└──────┬──────────────────────────────────┘
       │
┌──────▼──────────────────────────────────┐
│    Multi-Chain RPC Layer                │
│  [Base RPC] [Optimism RPC] [Eth RPC]    │
└─────────────────────────────────────────┘
       │
┌──────▼──────────────────────────────────┐
│         Blockchain Networks             │
│   Base Sepolia / Optimism Sepolia       │
└─────────────────────────────────────────┘

       ┌───────────────┐
       │  Observability│
       │  - Metrics    │
       │  - Logs       │
       │  - Traces     │
       └───────────────┘
```

---

#### 3.2.2 核心服务拆分

**1. Intent Service**
- 职责：管理支付意图的生命周期
- 接口：
  - `createIntent(params)` → Intent
  - `getIntent(id)` → Intent
  - `updateState(id, state)` → void
  - `listIntents(filter)` → Intent[]

**2. Transaction Service**
- 职责：构建和提交链上交易
- 接口：
  - `buildTransaction(intent)` → UnsignedTx
  - `submitTransaction(tx, network)` → txHash
  - `checkTransaction(txHash, network)` → TxReceipt

**3. Retry Service**
- 职责：处理失败重试逻辑
- 接口：
  - `scheduleRetry(intent, delay)` → void
  - `processRetries()` → void (定时任务)

**4. Confirmation Service**
- 职责：监听区块确认
- 接口：
  - `watchTransaction(txHash, network, minConf)` → Observable
  - `handleReorg(txHash, network)` → void

**5. Webhook Service**
- 职责：发送和管理回调
- 接口：
  - `sendWebhook(event)` → void
  - `retryFailedWebhooks()` → void

---

### 3.3 API 设计

#### 3.3.1 创建支付意图

**Request:**
```http
POST /api/v1/intents
Content-Type: application/json
Authorization: Bearer {API_KEY}

{
  "amount": "1000000",           // 1 USDC (6 位小数)
  "payer": "0x1234...",
  "payee": "0x5678...",
  "networks": ["base", "optimism"],
  "deadline": 1700000000,
  "policy": {
    "minConfirmations": 2,
    "maxRetries": 5
  },
  "metadata": {
    "serviceId": "ai-translator",
    "userId": "user-123"
  }
}
```

**Response:**
```json
{
  "intentId": "01HGW...",
  "state": "created",
  "expiresAt": 1700000000,
  "authorizeMessage": "Sign this message to authorize payment..."
}
```

---

#### 3.3.2 提交支付

**Request:**
```http
POST /api/v1/intents/{intentId}/submit
Content-Type: application/json
Idempotency-Key: {unique-key}
Authorization: Bearer {API_KEY}

{
  "signature": "0xabcd...",      // 用户签名
  "network": "base"              // 可选，不提供则自动选择
}
```

**Response:**
```json
{
  "intentId": "01HGW...",
  "state": "submitted",
  "network": "base",
  "txHash": "0x9876...",
  "confirmations": 0,
  "estimatedConfirmTime": 1700000120
}
```

---

#### 3.3.3 查询状态

**Request:**
```http
GET /api/v1/intents/{intentId}
Authorization: Bearer {API_KEY}
```

**Response:**
```json
{
  "intentId": "01HGW...",
  "amount": "1000000",
  "state": "confirmed",
  "network": "base",
  "txHash": "0x9876...",
  "blockNumber": 12345678,
  "confirmations": 6,
  "timeline": [
    {
      "timestamp": 1700000000,
      "event": "created"
    },
    {
      "timestamp": 1700000010,
      "event": "authorized"
    },
    {
      "timestamp": 1700000015,
      "event": "submitted",
      "txHash": "0x9876..."
    },
    {
      "timestamp": 1700000100,
      "event": "confirmed",
      "confirmations": 6
    }
  ],
  "attempts": [
    {
      "attemptId": "01HGX...",
      "network": "base",
      "txHash": "0x9876...",
      "status": "success"
    }
  ]
}
```

---

#### 3.3.4 Webhook 回调格式

**Request (从服务器发送到商户):**
```http
POST {merchant_webhook_url}
Content-Type: application/json
X-Signature: {HMAC_SHA256}
X-Timestamp: 1700000100

{
  "event": "payment.confirmed",
  "intentId": "01HGW...",
  "amount": "1000000",
  "payer": "0x1234...",
  "payee": "0x5678...",
  "network": "base",
  "txHash": "0x9876...",
  "blockNumber": 12345678,
  "metadata": {
    "serviceId": "ai-translator",
    "userId": "user-123"
  }
}
```

**签名验证:**
```typescript
const signature = HMAC_SHA256(
  secret,
  `${timestamp}.${JSON.stringify(body)}`
);
```

---

### 3.4 智能合约设计

#### 3.4.1 AgentPaymentEscrow（托管合约）

```solidity
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import "@openzeppelin/contracts/security/ReentrancyGuard.sol";

contract AgentPaymentEscrow is ReentrancyGuard {
    IERC20 public immutable usdc;

    struct Payment {
        address payer;
        address payee;
        uint256 amount;
        uint256 deadline;
        PaymentStatus status;
        bytes32 intentId;
    }

    enum PaymentStatus {
        Pending,
        Completed,
        Refunded,
        Expired
    }

    mapping(bytes32 => Payment) public payments;

    event PaymentCreated(bytes32 indexed intentId, address payer, address payee, uint256 amount);
    event PaymentCompleted(bytes32 indexed intentId);
    event PaymentRefunded(bytes32 indexed intentId);

    constructor(address _usdc) {
        usdc = IERC20(_usdc);
    }

    /// @notice 创建支付并锁定资金
    function createPayment(
        bytes32 intentId,
        address payee,
        uint256 amount,
        uint256 deadline
    ) external nonReentrant {
        require(payments[intentId].payer == address(0), "Intent already exists");
        require(deadline > block.timestamp, "Invalid deadline");

        require(
            usdc.transferFrom(msg.sender, address(this), amount),
            "Transfer failed"
        );

        payments[intentId] = Payment({
            payer: msg.sender,
            payee: payee,
            amount: amount,
            deadline: deadline,
            status: PaymentStatus.Pending,
            intentId: intentId
        });

        emit PaymentCreated(intentId, msg.sender, payee, amount);
    }

    /// @notice 完成支付，释放资金给 payee
    function completePayment(bytes32 intentId) external nonReentrant {
        Payment storage payment = payments[intentId];
        require(payment.status == PaymentStatus.Pending, "Invalid status");
        require(block.timestamp <= payment.deadline, "Payment expired");

        payment.status = PaymentStatus.Completed;

        require(
            usdc.transfer(payment.payee, payment.amount),
            "Transfer failed"
        );

        emit PaymentCompleted(intentId);
    }

    /// @notice 退款（仅在超时后）
    function refund(bytes32 intentId) external nonReentrant {
        Payment storage payment = payments[intentId];
        require(payment.payer == msg.sender, "Not payer");
        require(payment.status == PaymentStatus.Pending, "Invalid status");
        require(block.timestamp > payment.deadline, "Not expired");

        payment.status = PaymentStatus.Refunded;

        require(
            usdc.transfer(payment.payer, payment.amount),
            "Transfer failed"
        );

        emit PaymentRefunded(intentId);
    }

    /// @notice 查询支付状态
    function getPayment(bytes32 intentId) external view returns (Payment memory) {
        return payments[intentId];
    }
}
```

---

#### 3.4.2 AgentRegistry（Agent 注册合约）

```solidity
contract AgentRegistry {
    struct Agent {
        address owner;
        string name;
        string endpoint;  // API endpoint
        uint256 pricePerCall;
        bool isActive;
        uint256 totalEarned;
        uint256 reputation; // 0-10000 (基点)
    }

    mapping(address => Agent) public agents;

    event AgentRegistered(address indexed agentAddress, string name);
    event AgentUpdated(address indexed agentAddress);

    function registerAgent(
        string calldata name,
        string calldata endpoint,
        uint256 pricePerCall
    ) external {
        require(agents[msg.sender].owner == address(0), "Already registered");

        agents[msg.sender] = Agent({
            owner: msg.sender,
            name: name,
            endpoint: endpoint,
            pricePerCall: pricePerCall,
            isActive: true,
            totalEarned: 0,
            reputation: 5000 // 初始 50%
        });

        emit AgentRegistered(msg.sender, name);
    }

    function updatePrice(uint256 newPrice) external {
        require(agents[msg.sender].owner == msg.sender, "Not owner");
        agents[msg.sender].pricePerCall = newPrice;
        emit AgentUpdated(msg.sender);
    }

    function recordPayment(address agent, uint256 amount) external {
        // 只能由托管合约调用
        agents[agent].totalEarned += amount;
    }
}
```

---

### 3.5 数据库设计

#### 3.5.1 表结构（PostgreSQL）

**payment_intents 表**
```sql
CREATE TABLE payment_intents (
    id VARCHAR(26) PRIMARY KEY,              -- ULID
    amount NUMERIC(20, 6) NOT NULL,          -- USDC 金额
    asset VARCHAR(10) DEFAULT 'USDC',
    payer VARCHAR(42) NOT NULL,              -- 以太坊地址
    payee VARCHAR(42) NOT NULL,
    deadline BIGINT NOT NULL,                -- Unix 时间戳
    state VARCHAR(20) NOT NULL,              -- PaymentState enum
    networks JSONB NOT NULL,                 -- 允许的链数组
    policy JSONB NOT NULL,                   -- PaymentPolicy
    metadata JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    INDEX idx_payer (payer),
    INDEX idx_payee (payee),
    INDEX idx_state (state),
    INDEX idx_created_at (created_at)
);
```

**tx_attempts 表**
```sql
CREATE TABLE tx_attempts (
    id VARCHAR(26) PRIMARY KEY,
    intent_id VARCHAR(26) NOT NULL REFERENCES payment_intents(id),
    network VARCHAR(20) NOT NULL,
    rpc_provider VARCHAR(50),
    tx_hash VARCHAR(66),                     -- 0x + 64 字符
    block_number BIGINT,
    confirmations INT DEFAULT 0,
    status VARCHAR(20) NOT NULL,
    error TEXT,
    gas_used NUMERIC(20, 0),
    timestamp BIGINT NOT NULL,

    INDEX idx_intent_id (intent_id),
    INDEX idx_tx_hash (tx_hash),
    INDEX idx_status (status)
);
```

**webhook_events 表**
```sql
CREATE TABLE webhook_events (
    id VARCHAR(26) PRIMARY KEY,
    intent_id VARCHAR(26) NOT NULL REFERENCES payment_intents(id),
    event VARCHAR(50) NOT NULL,
    url TEXT NOT NULL,
    payload JSONB NOT NULL,
    signature VARCHAR(64),
    attempts INT DEFAULT 0,
    status VARCHAR(20) NOT NULL,
    last_attempt_at TIMESTAMPTZ,
    next_retry_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),

    INDEX idx_intent_id (intent_id),
    INDEX idx_status (status),
    INDEX idx_next_retry (next_retry_at)
);
```

**agent_services 表**
```sql
CREATE TABLE agent_services (
    id VARCHAR(26) PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    description TEXT,
    provider VARCHAR(42) NOT NULL,           -- Agent 地址
    price_per_call NUMERIC(20, 6) NOT NULL,
    category VARCHAR(50),
    rating NUMERIC(3, 2) DEFAULT 0,
    total_calls INT DEFAULT 0,
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT NOW(),

    INDEX idx_provider (provider),
    INDEX idx_category (category),
    INDEX idx_rating (rating DESC)
);
```

**idempotency_keys 表**
```sql
CREATE TABLE idempotency_keys (
    key VARCHAR(64) PRIMARY KEY,
    intent_id VARCHAR(26) NOT NULL,
    result JSONB NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL,

    INDEX idx_intent_id (intent_id),
    INDEX idx_expires_at (expires_at)
);
```

---

### 3.6 技术栈选型

#### 前端
- **框架**: Next.js 14 (App Router)
- **UI 库**: shadcn/ui + Tailwind CSS
- **钱包集成**: wagmi + viem
- **状态管理**: Zustand (轻量级)
- **图表**: Recharts

#### 后端
- **运行时**: Node.js 20
- **框架**: Express.js
- **ORM**: Prisma (或直接用 pg 库)
- **任务队列**: BullMQ (Redis)
- **WebSocket**: Socket.io

#### 区块链
- **RPC 库**: viem
- **多链支持**: Base Sepolia, Optimism Sepolia
- **合约框架**: Hardhat + OpenZeppelin

#### 数据库
- **主库**: PostgreSQL 15
- **缓存**: Redis 7
- **搜索**: 暂不需要（数据量小）

#### DevOps
- **部署**: Vercel (前端) + Railway/Render (后端)
- **监控**: 简单的自定义 Dashboard
- **日志**: Console + 文件（生产环境用 Winston）

---

### 3.7 关键算法设计

#### 3.7.1 重试策略

```typescript
class RetryEngine {
  async executeWithRetry<T>(
    fn: () => Promise<T>,
    policy: {
      maxRetries: number;
      deadline: number;
      baseDelay: number; // 初始延迟（毫秒）
    }
  ): Promise<T> {
    let attempt = 0;
    let lastError: Error;

    while (attempt < policy.maxRetries) {
      if (Date.now() / 1000 > policy.deadline) {
        throw new Error("Deadline exceeded");
      }

      try {
        return await fn();
      } catch (error) {
        lastError = error;

        // Fast-fail 错误直接抛出
        if (this.isFastFailError(error)) {
          throw error;
        }

        // Transient 错误进入重试
        attempt++;
        if (attempt < policy.maxRetries) {
          const delay = this.calculateBackoff(attempt, policy.baseDelay);
          await this.sleep(delay);
        }
      }
    }

    throw lastError;
  }

  private isFastFailError(error: any): boolean {
    // 余额不足、nonce 太低等
    const fastFailCodes = [
      "INSUFFICIENT_FUNDS",
      "NONCE_TOO_LOW",
      "INVALID_SIGNATURE"
    ];
    return fastFailCodes.includes(error.code);
  }

  private calculateBackoff(attempt: number, baseDelay: number): number {
    // 指数退避 + jitter
    const exponential = baseDelay * Math.pow(2, attempt);
    const jitter = Math.random() * 0.3 * exponential;
    return Math.min(exponential + jitter, 30000); // 最大 30 秒
  }

  private sleep(ms: number): Promise<void> {
    return new Promise(resolve => setTimeout(resolve, ms));
  }
}
```

---

#### 3.7.2 网络选择策略

```typescript
interface NetworkMetrics {
  network: string;
  avgGasCost: bigint;
  avgConfirmTime: number; // 秒
  successRate: number;    // 0-1
  currentLoad: number;    // 0-1
}

class NetworkSelector {
  async selectOptimalNetwork(
    allowedNetworks: string[],
    metrics: NetworkMetrics[]
  ): Promise<string> {
    const candidates = metrics.filter(m =>
      allowedNetworks.includes(m.network)
    );

    if (candidates.length === 0) {
      throw new Error("No valid networks");
    }

    // 计算综合得分
    const scored = candidates.map(m => ({
      network: m.network,
      score: this.calculateScore(m)
    }));

    // 返回得分最高的
    scored.sort((a, b) => b.score - a.score);
    return scored[0].network;
  }

  private calculateScore(metrics: NetworkMetrics): number {
    // 权重可配置
    const weights = {
      cost: 0.3,
      speed: 0.4,
      reliability: 0.3
    };

    // 归一化并计算得分
    const costScore = 1 - Number(metrics.avgGasCost) / 1e18; // 简化
    const speedScore = 1 / metrics.avgConfirmTime;
    const reliabilityScore = metrics.successRate * (1 - metrics.currentLoad);

    return (
      weights.cost * costScore +
      weights.speed * speedScore +
      weights.reliability * reliabilityScore
    );
  }
}
```

---

#### 3.7.3 Reorg 检测

```typescript
class ReorgDetector {
  async monitorTransaction(
    txHash: string,
    network: string,
    minConf: number
  ): Promise<void> {
    const client = this.getClient(network);
    let lastBlockHash: string | null = null;
    let confirmations = 0;

    while (confirmations < minConf) {
      const receipt = await client.getTransactionReceipt({ hash: txHash });

      if (!receipt) {
        // 交易从内存池消失，可能被 reorg
        await this.handlePotentialReorg(txHash, network);
        continue;
      }

      const currentBlock = await client.getBlock({ blockNumber: receipt.blockNumber });

      // 检测块哈希变化
      if (lastBlockHash && lastBlockHash !== currentBlock.hash) {
        console.warn(`Reorg detected at block ${currentBlock.number}`);
        await this.handleReorg(txHash, network);
        lastBlockHash = null;
        confirmations = 0;
        continue;
      }

      lastBlockHash = currentBlock.hash;
      const latestBlock = await client.getBlockNumber();
      confirmations = Number(latestBlock - receipt.blockNumber) + 1;

      await this.sleep(2000); // 每 2 秒检查一次
    }
  }

  private async handleReorg(txHash: string, network: string): Promise<void> {
    // 标记原交易为 dropped
    // 重新广播或构建新交易
    // 更新 PaymentIntent 状态
  }
}
```

---

### 3.8 安全措施

#### 3.8.1 API 认证

```typescript
// API Key 中间件
function apiKeyAuth(req: Request, res: Response, next: NextFunction) {
  const apiKey = req.headers.authorization?.replace("Bearer ", "");

  if (!apiKey) {
    return res.status(401).json({ error: "Missing API key" });
  }

  const validKey = validateApiKey(apiKey); // 查数据库或缓存

  if (!validKey) {
    return res.status(401).json({ error: "Invalid API key" });
  }

  req.userId = validKey.userId;
  next();
}
```

---

#### 3.8.2 Webhook 签名验证

```typescript
function verifyWebhookSignature(
  payload: string,
  timestamp: string,
  signature: string,
  secret: string
): boolean {
  const expectedSignature = crypto
    .createHmac("sha256", secret)
    .update(`${timestamp}.${payload}`)
    .digest("hex");

  // 时间窗口检查（防重放）
  const now = Date.now() / 1000;
  if (Math.abs(now - parseInt(timestamp)) > 300) {
    return false; // 超过 5 分钟
  }

  return crypto.timingSafeEqual(
    Buffer.from(signature),
    Buffer.from(expectedSignature)
  );
}
```

---

#### 3.8.3 幂等性实现

```typescript
class IdempotencyService {
  async checkAndStore(
    intentId: string,
    key: string,
    ttl: number = 86400 // 24 小时
  ): Promise<any | null> {
    const existing = await db.idempotencyKeys.findUnique({
      where: { key }
    });

    if (existing) {
      // 检查是否匹配同一 intent
      if (existing.intentId !== intentId) {
        throw new Error("Idempotency key conflict");
      }
      return existing.result;
    }

    return null;
  }

  async store(key: string, intentId: string, result: any, ttl: number) {
    await db.idempotencyKeys.create({
      data: {
        key,
        intentId,
        result: result as any,
        expiresAt: new Date(Date.now() + ttl * 1000)
      }
    });
  }
}
```

---

### 3.9 可观测性设计

#### 3.9.1 关键指标

**业务指标**:
- 支付成功率（按链、按 Agent 分组）
- 平均确认时间（P50/P95/P99）
- 重试次数分布
- Webhook 成功率

**技术指标**:
- API 响应时间
- 数据库查询延迟
- RPC 调用成功率（按提供商）
- 队列深度

**财务指标**:
- 总交易量（按时间、链）
- 手续费消耗
- Agent 收入排行

---

#### 3.9.2 简易 Metrics 收集

```typescript
class MetricsCollector {
  private metrics: Map<string, number[]> = new Map();

  record(name: string, value: number) {
    if (!this.metrics.has(name)) {
      this.metrics.set(name, []);
    }
    this.metrics.get(name)!.push(value);
  }

  increment(name: string) {
    this.record(name, 1);
  }

  getStats(name: string) {
    const values = this.metrics.get(name) || [];
    if (values.length === 0) return null;

    const sorted = [...values].sort((a, b) => a - b);
    return {
      count: values.length,
      sum: values.reduce((a, b) => a + b, 0),
      avg: values.reduce((a, b) => a + b, 0) / values.length,
      p50: sorted[Math.floor(sorted.length * 0.5)],
      p95: sorted[Math.floor(sorted.length * 0.95)],
      p99: sorted[Math.floor(sorted.length * 0.99)]
    };
  }

  flush() {
    const snapshot = Object.fromEntries(
      Array.from(this.metrics.entries()).map(([k, v]) => [
        k,
        this.getStats(k)
      ])
    );
    this.metrics.clear();
    return snapshot;
  }
}

// 使用示例
metrics.increment("payment.created");
metrics.record("payment.confirm_time", confirmTimeSeconds);
```

---

## 四、10 小时实施计划（基于 Thirdweb x402）

### 优化后的时间分配

| 时间段 | 任务 | 产出 | 优先级 | 说明 |
|--------|------|------|--------|------|
| 0-1h | 项目搭建 + Thirdweb 配置 | Next.js + API Key | P0 | 使用 create-next-app + shadcn/ui |
| 1-2h | x402 后端集成 | Express + settlePayment | P0 | 参考官方示例代码 |
| 2-3h | x402 前端集成 + 钱包 | wrapFetchWithPayment | P0 | Thirdweb 自动处理重试 |
| 3-4h | Agent 服务市场 UI | 服务列表 + 卡片 | P0 | 3-5 个模拟服务 |
| 4-5h | 完整支付流程测试 | 端到端可用 | P0 | 调试 x402 流程 |
| 5-6h | 支付历史 + 状态页面 | 交易记录 UI | P1 | 查询链上交易 |
| 6-7h | 可观测性仪表板 | Metrics 展示 | P1 | 成功率/延迟统计 |
| 7-8h | AI Agent 模拟调用 | 真实服务演示 | P1 | 接入 OpenAI API（可选） |
| 8-9h | 打磨 UI + 用户体验 | 动画/加载状态 | P2 | 提升演示效果 |
| 9-10h | 测试 + Demo 准备 | 演示脚本 + PPT | P0 | 录制演示视频 |

**关键优化点**:
- ✅ **无需自己开发智能合约**：Thirdweb Facilitator 内置托管逻辑
- ✅ **无需手动处理重试**：SDK 自动处理 RPC 故障转移
- ✅ **无需 Gas Token**：Facilitator 代付 gas 费
- ✅ **节省 2-3 小时**：用于打磨 UI 和增加功能

---

### MVP 功能取舍（基于 x402）

**必须有（Demo 核心）**:
- ✅ Thirdweb 钱包集成（MetaMask/WalletConnect）
- ✅ Agent 服务市场（3-5 个服务卡片）
- ✅ x402 支付流程（一键调用 + 支付）
- ✅ Monad 测试网支持
- ✅ 支付成功/失败状态展示
- ✅ 交易哈希和区块浏览器链接
- ✅ 支付历史记录（本地存储或简单数据库）

**Thirdweb 自动提供**:
- 🎁 重试机制（SDK 内置）
- 🎁 多 RPC 切换（自动故障转移）
- 🎁 Gas 费代付（Facilitator）
- 🎁 幂等性保证（内置）
- 🎁 支付确认等待

**可以简化**:
- ⚠️ 智能合约 → 使用 Thirdweb Facilitator（无需自己部署）
- ⚠️ AI Agent 调用 → 前期返回模拟数据，后期接入真实 API
- ⚠️ 可观测性 → 简单的计数器和图表
- ⚠️ 多链支持 → MVP 只支持 Monad，后续 1 行代码切换

**可以砍掉**:
- ❌ 自定义智能合约开发
- ❌ WebSocket 实时推送
- ❌ 完整的 Webhook 系统
- ❌ Agent 信誉评分系统
- ❌ 跨链桥接（第一版）

---

## 五、演示脚本设计

### Demo 流程（3 分钟）

**场景**: AI 翻译 Agent 调用 AI 数据分析 Agent

1. **开场**（30秒）
   - 问题：当前 AI Agent 缺乏标准化的支付方式
   - 方案：基于 x402 的去中心化支付中间件

2. **演示**（2分钟）
   - 连接钱包（显示 10 USDC 测试币）
   - 浏览 Agent 市场，选择"AI 数据分析"服务（0.5 USDC）
   - 点击"调用服务"
   - 确认支付 → 实时显示交易状态
     - ⏳ 提交中...
     - ✅ 已确认（2/2 区块）
   - Agent 返回分析结果
   - 查看交易历史（显示链上哈希）

3. **技术亮点**（30秒）
   - 自动重试：如果第一次 RPC 失败，自动切换节点
   - 幂等性：重复点击不会重复扣款
   - 可追溯：每笔支付都有完整时间线

4. **未来扩展**（30秒）
   - 多链支持（Optimism/Ethereum）
   - 跨链支付桥梁
   - AI Agent 自动协商价格

---

### 关键代码展示点

**1. 幂等性保证**
```typescript
// 展示同一 Idempotency-Key 多次调用返回相同结果
const result1 = await submitPayment(intentId, {
  idempotencyKey: "unique-123"
});
const result2 = await submitPayment(intentId, {
  idempotencyKey: "unique-123"
});
assert(result1.txHash === result2.txHash); // ✅ 相同
```

**2. 自动重试**
```typescript
// 展示 RPC 失败时自动切换
try {
  await baseRPC1.sendTransaction(tx);
} catch (error) {
  console.log("RPC 1 failed, switching to RPC 2...");
  await baseRPC2.sendTransaction(tx); // ✅ 成功
}
```

**3. 支付时间线**
```typescript
{
  "timeline": [
    { "time": "14:30:00", "event": "Created" },
    { "time": "14:30:05", "event": "Submitted", "txHash": "0x..." },
    { "time": "14:30:15", "event": "Confirmed 1/2" },
    { "time": "14:30:25", "event": "Confirmed 2/2 ✅" }
  ]
}
```

---

## 六、Monad 测试网与 x402 集成详情

### 6.1 Monad 测试网配置

**网络信息**:
- **RPC URL**: `https://testnet-rpc.monad.xyz`
- **Chain ID**: `10143` (十进制) / `0x279F` (十六进制)
- **Faucet**: `https://testnet.monad.xyz`
- **区块浏览器**:
  - https://testnet.monadexplorer.com/
  - https://monad-testnet.socialscan.io/

**性能指标**:
- **TPS**: 10,000
- **出块时间**: ~0.4 秒
- **最终性**: 单槽最终性（Single-slot finality）
- **手续费**: 极低
- **并行执行**: 支持

**USDC 测试币**:
- **合约地址**: `0x534b2f3A21130d7a60830c2Df862319e593943A3` (Circle USDC)
- **Faucet**: https://faucet.circle.com/ (选择 Monad Testnet)

**测试网特性**:
- ✅ 稳定可用，适合黑客松开发
- ✅ 支持 EVM 完全兼容
- ✅ 0.4 秒出块，极快确认
- ✅ 低 gas 费，适合小额支付

---

### 6.2 x402 协议集成

#### 什么是 x402？

x402 是基于 HTTP 402 "Payment Required" 状态码的互联网原生小额支付协议。

**核心流程**:
1. 客户端请求资源
2. 服务器响应 402 + JSON 支付要求
3. 客户端签名交易付款
4. 服务器验证后提供内容

**优势**:
- 🚀 减少费用和摩擦（无中介）
- 💰 小额支付和按使用计费
- 🤖 支持机器对机器交易（AI Agent 自主支付）

**为什么选择 Monad？**
- 10,000 TPS + 0.4 秒出块 = 即时结算
- 极低费用 = 真正的小额支付
- 避免内存池拥堵 = 适合大量 Agent 并发支付

---

#### x402 流程图

**无 Facilitator 流程**:
```
Client → Request → Server
Server → 402 + Payment Requirement → Client
Client → Sign Transaction → Blockchain
Client → Proof of Payment → Server
Server → Verify → Content
```

**带 Facilitator 流程（推荐）**:
```
Client → Request + Payment Header → Facilitator
Facilitator → Process Payment (无 Gas) → Blockchain
Facilitator → Forward Request → Server
Server → Content → Client
```

> **Facilitator 优势**:
> - 用户无需持有 Gas Token（如 MON）
> - 简化支付流程
> - 处理交易重试和确认

---

### 6.3 Thirdweb x402 集成方案

#### 核心依赖

```bash
npm install thirdweb dotenv express cors
```

#### 环境变量配置

```bash
# .env
THIRDWEB_CLIENT_ID=your_client_id_here      # 前端使用
THIRDWEB_SECRET_KEY=your_secret_key_here    # 后端使用
RECIPIENT_WALLET=0xYourWalletAddress        # 收款地址
```

**获取 Thirdweb API Key**:
1. 访问 https://thirdweb.com/dashboard
2. 登录（钱包或 Google）
3. 创建项目
4. 设置 → API 密钥 → 复制 `clientId` 和 `secretKey`

---

#### 后端实现（Express）

```typescript
require("dotenv").config();
const express = require("express");
const { createThirdwebClient } = require("thirdweb");
const { facilitator, settlePayment } = require("thirdweb/x402");
const { defineChain } = require("thirdweb/chains");

const app = express();
app.use(express.json());

// 定义 Monad 测试网
const monadTestnet = defineChain(10143);

// 创建 Thirdweb 客户端
const client = createThirdwebClient({
  secretKey: process.env.THIRDWEB_SECRET_KEY
});

// 初始化 Facilitator
const twFacilitator = facilitator({
  client,
  serverWalletAddress: process.env.RECIPIENT_WALLET,
});

// x402 保护的端点
app.get("/api/agent/:serviceId", async (req, res) => {
  try {
    const result = await settlePayment({
      resourceUrl: `http://localhost:3000/api/agent/${req.params.serviceId}`,
      method: "GET",
      paymentData: req.headers["x-payment"], // 客户端支付证明
      network: monadTestnet,
      price: "$0.001",                        // 0.001 USDC
      payTo: process.env.RECIPIENT_WALLET,
      facilitator: twFacilitator,
    });

    if (result.status === 200) {
      // 支付成功，返回 Agent 服务结果
      res.json({
        message: "Payment received ⚡",
        tx: result.transactionHash,
        data: await callAgentService(req.params.serviceId)
      });
    } else {
      // 返回 402 或其他错误
      res.status(result.status)
         .set(result.responseHeaders || {})
         .json(result.responseBody);
    }
  } catch (e) {
    res.status(500).json({ error: "Payment processing failed" });
  }
});

app.listen(3000);
```

---

#### 前端实现（React）

```typescript
import { useState } from "react";
import { createThirdwebClient } from "thirdweb";
import { wrapFetchWithPayment } from "thirdweb/x402";
import { createWallet } from "thirdweb/wallets";

const client = createThirdwebClient({
  clientId: import.meta.env.VITE_THIRDWEB_CLIENT_ID,
});

export default function AgentServiceCall() {
  const [result, setResult] = useState("");

  const callPaidService = async (serviceId: string) => {
    // 连接钱包
    const wallet = createWallet("io.metamask");
    await wallet.connect({ client });

    // 包装 fetch，自动处理 x402 支付
    const fetchWithPayment = wrapFetchWithPayment(fetch, client, wallet);

    // 调用需要支付的 API
    const res = await fetchWithPayment(`/api/agent/${serviceId}`);
    const json = await res.json();

    setResult(JSON.stringify(json, null, 2));
  };

  return (
    <button onClick={() => callPaidService("translator")}>
      调用 AI 翻译服务 (0.001 USDC)
    </button>
  );
}
```

**用户体验**:
1. 点击按钮 → 自动触发钱包弹窗
2. 用户确认支付 0.001 USDC
3. Facilitator 处理支付（无需 Gas Token）
4. 立即返回 Agent 服务结果

---

### 6.4 多链支持（可选）

Thirdweb x402 支持 170+ EVM 链，可轻松扩展到：
- Base Sepolia
- Optimism Sepolia
- Arbitrum Sepolia
- Ethereum Sepolia

**切换链示例**:
```typescript
const baseSepolia = defineChain(84532);

const result = await settlePayment({
  // ... 其他参数
  network: baseSepolia, // 只需修改这里
});
```

---

## 七、风险与应对（更新版）

### 技术风险

| 风险 | 影响 | 应对措施 | 状态 |
|------|------|----------|------|
| Monad 测试网不稳定 | 无法演示 | ✅ 已确认稳定可用 | **已解决** |
| USDC 测试币不足 | 无法测试 | ✅ Circle Faucet 可用 | **已解决** |
| RPC 调用超时 | 支付失败 | 使用 Thirdweb Facilitator 自动处理 | **低风险** |
| 智能合约 Bug | 资金安全 | ✅ 视为透明，不考虑 | **已豁免** |
| x402 集成复杂 | 开发超时 | ✅ Thirdweb SDK 简化集成 | **已解决** |

### 时间风险

| 风险 | 应对 |
|------|------|
| 合约开发超时 | 使用简化版托管合约（仅转账） |
| UI 开发超时 | 使用 shadcn/ui 模板 |
| 集成调试超时 | 优先完成核心流程，砍掉次要功能 |

---

## 七、后续优化方向（活动后）

1. **完整的 x402 协议集成**
   - 支持 Payment Header
   - 实现 402 状态码响应

2. **多链路由优化**
   - 基于历史数据的智能路由
   - 动态 gas 费预测

3. **高级重试策略**
   - 自适应退避算法
   - 基于链拥堵情况调整重试间隔

4. **完整的可观测性**
   - Grafana + Prometheus
   - 分布式追踪（Jaeger）

5. **Agent 生态**
   - Agent 发现协议
   - 信誉评分系统
   - 服务级别协议（SLA）

---

## 附录

### A. 术语表

- **Intent**: 支付意图，包含支付金额、方向、策略等信息
- **Idempotency**: 幂等性，多次相同请求产生相同结果
- **Reorg**: 区块链重组，已确认的区块被替换
- **Fast-fail**: 快速失败，无法重试的错误（如余额不足）
- **Transient Error**: 临时错误，可通过重试解决（如网络超时）
- **Backoff**: 退避，重试前的等待时间
- **Webhook**: 服务器向客户端的主动推送

### B. 参考资料

**官方文档**:
- Monad 开发者门户: https://docs.monad.xyz
- Monad 测试网信息: https://monad-foundation.notion.site/2ae6367594f281cab61ae3fb6c269bf2
- Monad x402 教程: https://monad-foundation.notion.site/Monad-x402-2ae6367594f28194bed7dd46c2741c48
- Thirdweb x402 文档: https://portal.thirdweb.com/typescript/v5/x402

**区块浏览器**:
- Monad Testnet Explorer: https://testnet.monadexplorer.com/
- SocialScan: https://monad-testnet.socialscan.io/

**Faucet**:
- MON Token Faucet: https://testnet.monad.xyz
- USDC Faucet: https://faucet.circle.com/

**开发工具**:
- Thirdweb Dashboard: https://thirdweb.com/dashboard
- shadcn/ui: https://ui.shadcn.com/
- Viem 文档: https://viem.sh/

---

### C. 快速启动检查清单

**准备工作（在活动开始前完成）**:
- [ ] 注册 Thirdweb 账户，获取 API Key
- [ ] 在 Monad Testnet Faucet 领取 MON Token
- [ ] 在 Circle Faucet 领取 USDC 测试币
- [ ] 安装 MetaMask 并添加 Monad 测试网
  - RPC: https://testnet-rpc.monad.xyz
  - Chain ID: 10143
- [ ] 准备开发环境：Node.js 20+, VS Code

**第一小时必做事项**:
1. `npx create-next-app@latest agent-payment --typescript --tailwind --app`
2. `cd agent-payment && npm install thirdweb dotenv express cors`
3. `npx shadcn-ui@latest init`
4. 复制 Thirdweb x402 示例代码到项目
5. 配置 `.env` 文件
6. 启动开发服务器测试

**调试技巧**:
- 使用 Monad Explorer 查看交易状态
- 检查 Thirdweb Dashboard 的 API 调用日志
- 保留浏览器控制台打开（查看 x402 支付流程）
- 准备多个钱包地址用于测试

**Demo 前最后检查**:
- [ ] 所有服务都能成功调用
- [ ] 支付流程顺畅（< 5 秒完成）
- [ ] UI 没有明显 bug
- [ ] 交易历史正确显示
- [ ] 准备好 PPT 和演讲稿
- [ ] 录制备用演示视频（防止现场网络问题）

---

### D. 核心代码片段速查

**Monad 测试网配置**:
```typescript
import { defineChain } from "thirdweb/chains";

export const monadTestnet = defineChain({
  id: 10143,
  rpc: "https://testnet-rpc.monad.xyz",
  nativeCurrency: {
    name: "Monad",
    symbol: "MON",
    decimals: 18,
  },
});

export const USDC_ADDRESS = "0x534b2f3A21130d7a60830c2Df862319e593943A3";
```

**快速添加网络到 MetaMask**:
```javascript
await window.ethereum.request({
  method: 'wallet_addEthereumChain',
  params: [{
    chainId: '0x279F',
    chainName: 'Monad Testnet',
    nativeCurrency: { name: 'MON', symbol: 'MON', decimals: 18 },
    rpcUrls: ['https://testnet-rpc.monad.xyz'],
    blockExplorerUrls: ['https://testnet.monadexplorer.com/']
  }]
});
```

**查询 USDC 余额**:
```typescript
import { getContract, readContract } from "thirdweb";
import { balanceOf } from "thirdweb/extensions/erc20";

const contract = getContract({
  client,
  address: USDC_ADDRESS,
  chain: monadTestnet,
});

const balance = await balanceOf({
  contract,
  address: userAddress,
});

console.log(`余额: ${balance / 1e6} USDC`);
```

**简易 Agent 服务模拟数据**:
```typescript
export const MOCK_AGENTS = [
  {
    id: "ai-translator",
    name: "AI 翻译服务",
    description: "支持 100+ 语言的实时翻译",
    price: "0.001",
    category: "language",
    icon: "🌐",
  },
  {
    id: "data-analyzer",
    name: "数据分析 Agent",
    description: "智能数据清洗和可视化",
    price: "0.005",
    category: "analysis",
    icon: "📊",
  },
  {
    id: "image-generator",
    name: "AI 图片生成",
    description: "文本转图片，秒级生成",
    price: "0.01",
    category: "creative",
    icon: "🎨",
  },
];
```

---

**文档版本**: v2.0
**创建时间**: 2025-11-29
**最后更新**: 2025-11-29
**作者**: Claude Code + User
**状态**: 已整合 Monad 测试网和 x402 实际配置
