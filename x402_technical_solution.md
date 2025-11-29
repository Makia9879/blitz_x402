# x402 协议技术风险解决方案

## 一、技术风险问题分析

基于 README.md 中提出的技术风险：

> - x402 是什么？项目中怎么体现 x402？以何种形式展示 x402？

## 二、x402 协议详解

### 2.1 什么是 x402？

**x402** 是一个基于 HTTP 协议的互联网原生支付标准，由 Coinbase 开发并开源。

**核心特点：**

1. **HTTP 原生集成**：使用 HTTP 402 "Payment Required" 状态码
2. **区块链支付**：支持 USDC 等稳定币支付
3. **无需账户系统**：客户端和服务器无需预先注册或订阅
4. **零手续费**：协议本身不收取任何费用
5. **即时结算**：支付在 2 秒内完成（取决于区块链速度）
6. **AI Agent 友好**：特别适合机器对机器的自动支付

**技术原理：**

```
传统 API 调用：
Client ---HTTP GET---> Server ---200 OK + Data--->

x402 支付流程：
Client ---HTTP GET---> Server ---402 Payment Required--->
                                 (包含支付要求)
Client ---签名交易---> Blockchain
Client ---带支付凭证的请求---> Server ---200 OK + Data--->
```

### 2.2 x402 与本项目的契合点

| 项目需求 | x402 协议如何满足 |
|---------|------------------|
| CC 中转站提供服务 | x402 标准化支付接口 |
| 用户充值额度 | USDC 链上充值，透明可追溯 |
| 额度统计 | 每笔交易都有链上记录 |
| MCP 工具集成 | x402 支持 HTTP 标准，易于集成 |
| 智能合约转账 | x402 使用 USDC ERC20 转账 |

## 三、项目中如何体现 x402

### 3.1 系统架构中的 x402 集成

```
┌─────────────────────────────────────────────────────────┐
│                    用户界面 (中转站 UI)                    │
│  - 显示额度余额                                           │
│  - 充值界面 (数字钱包插件)                                │
│  - x402 支付历史记录                                      │
└────────────────────┬────────────────────────────────────┘
                     │ WebSocket + HTTP
┌────────────────────▼────────────────────────────────────┐
│              MCP 工具 (x402 客户端实现)                    │
│  - wrapFetchWithPayment() 自动处理 x402                  │
│  - 钱包签名支付                                           │
│  - 支付状态追踪                                           │
└────────────────────┬────────────────────────────────────┘
                     │ HTTP + x402 Headers
┌────────────────────▼────────────────────────────────────┐
│           中转站后台 (x402 服务端实现)                      │
│  - settlePayment() 验证支付                              │
│  - 额度管理和统计                                         │
│  - 返回 402 状态码 + 支付要求                             │
└────────────────────┬────────────────────────────────────┘
                     │
        ┌────────────┴────────────┐
        │                         │
┌───────▼──────┐         ┌────────▼────────┐
│ Thirdweb     │         │   智能合约      │
│ Facilitator  │         │  (USDC ERC20)   │
│  - 处理支付   │         │  - 代币转账     │
│  - 无需 Gas   │         │  - 余额查询     │
└──────────────┘         └─────────────────┘
        │                         │
        └────────────┬────────────┘
                     │
              ┌──────▼──────┐
              │ Monad 测试网 │
              │  10,000 TPS  │
              │  0.4s 出块   │
              └──────────────┘
```

### 3.2 核心代码实现

#### 3.2.1 MCP 工具 - x402 客户端

```typescript
// mcp_tool/src/x402-client.ts

import { createThirdwebClient } from "thirdweb";
import { wrapFetchWithPayment } from "thirdweb/x402";
import { createWallet } from "thirdweb/wallets";

// 初始化 Thirdweb 客户端
const client = createThirdwebClient({
  clientId: process.env.THIRDWEB_CLIENT_ID,
});

/**
 * MCP 工具调用 CC 服务的 x402 包装器
 */
export async function callCCServiceWithPayment(
  serviceEndpoint: string,
  walletInstance: any
) {
  // 使用 x402 包装 fetch
  const fetchWithPayment = wrapFetchWithPayment(
    fetch,
    client,
    walletInstance
  );

  try {
    // 调用中转站的 CC 服务
    const response = await fetchWithPayment(serviceEndpoint, {
      method: "GET",
      headers: {
        "Content-Type": "application/json",
      },
    });

    if (response.status === 200) {
      const result = await response.json();
      return {
        success: true,
        data: result.data,
        txHash: result.tx,
        cost: result.cost,
      };
    } else {
      throw new Error(`Payment failed: ${response.statusText}`);
    }
  } catch (error) {
    console.error("x402 payment error:", error);
    throw error;
  }
}

/**
 * 用户充值额度到中转站
 */
export async function rechargeCredits(
  amount: string, // USDC 金额
  userWallet: any
) {
  const rechargeEndpoint = `${CC_RELAY_URL}/api/recharge`;

  return await callCCServiceWithPayment(rechargeEndpoint, userWallet);
}
```

#### 3.2.2 中转站后台 - x402 服务端

```typescript
// relay_backend/src/x402-server.ts

import express from "express";
import { createThirdwebClient } from "thirdweb";
import { facilitator, settlePayment } from "thirdweb/x402";
import { defineChain } from "thirdweb/chains";

const app = express();
app.use(express.json());

// 定义 Monad 测试网
const monadTestnet = defineChain(10143);

// 创建 Thirdweb 服务端客户端
const client = createThirdwebClient({
  secretKey: process.env.THIRDWEB_SECRET_KEY,
});

// 初始化 x402 Facilitator
const twFacilitator = facilitator({
  client,
  serverWalletAddress: process.env.RELAY_WALLET_ADDRESS,
});

/**
 * x402 保护的 CC 服务端点
 */
app.get("/api/cc/:modelName", async (req, res) => {
  const { modelName } = req.params;

  // 获取服务价格
  const servicePrice = getServicePrice(modelName); // 例如 "0.001" USDC

  try {
    const result = await settlePayment({
      resourceUrl: `${process.env.RELAY_URL}/api/cc/${modelName}`,
      method: "GET",
      paymentData: req.headers["x-payment"], // x402 支付数据
      network: monadTestnet,
      price: `$${servicePrice}`,
      payTo: process.env.RELAY_WALLET_ADDRESS,
      facilitator: twFacilitator,
    });

    if (result.status === 200) {
      // 支付成功，扣除用户额度
      await deductUserCredits(
        result.payer,
        servicePrice,
        result.transactionHash
      );

      // 调用实际的 CC 模型服务
      const ccResponse = await callCCModel(modelName, req.query);

      // 返回结果
      res.json({
        success: true,
        data: ccResponse,
        tx: result.transactionHash,
        cost: servicePrice,
        blockNumber: result.blockNumber,
      });
    } else {
      // 返回 402 支付要求
      res
        .status(result.status)
        .set(result.responseHeaders || {})
        .json(result.responseBody);
    }
  } catch (error) {
    console.error("Payment settlement failed:", error);
    res.status(500).json({ error: "Payment processing error" });
  }
});

/**
 * 用户充值额度端点
 */
app.post("/api/recharge", async (req, res) => {
  const rechargeAmount = req.body.amount; // USDC 金额

  try {
    const result = await settlePayment({
      resourceUrl: `${process.env.RELAY_URL}/api/recharge`,
      method: "POST",
      paymentData: req.headers["x-payment"],
      network: monadTestnet,
      price: `$${rechargeAmount}`,
      payTo: process.env.RELAY_WALLET_ADDRESS,
      facilitator: twFacilitator,
    });

    if (result.status === 200) {
      // 增加用户额度
      await addUserCredits(
        result.payer,
        rechargeAmount,
        result.transactionHash
      );

      res.json({
        success: true,
        newBalance: await getUserCredits(result.payer),
        tx: result.transactionHash,
      });
    } else {
      res
        .status(result.status)
        .set(result.responseHeaders || {})
        .json(result.responseBody);
    }
  } catch (error) {
    res.status(500).json({ error: "Recharge failed" });
  }
});

// 额度管理函数
async function deductUserCredits(userAddress: string, amount: string, txHash: string) {
  // 从数据库扣除用户额度
  await db.userCredits.update({
    where: { address: userAddress },
    data: {
      balance: { decrement: parseFloat(amount) },
      transactions: {
        create: {
          type: "deduct",
          amount: parseFloat(amount),
          txHash,
          timestamp: new Date(),
        },
      },
    },
  });
}

async function addUserCredits(userAddress: string, amount: string, txHash: string) {
  // 增加用户额度
  await db.userCredits.upsert({
    where: { address: userAddress },
    create: {
      address: userAddress,
      balance: parseFloat(amount),
      transactions: {
        create: {
          type: "recharge",
          amount: parseFloat(amount),
          txHash,
          timestamp: new Date(),
        },
      },
    },
    update: {
      balance: { increment: parseFloat(amount) },
      transactions: {
        create: {
          type: "recharge",
          amount: parseFloat(amount),
          txHash,
          timestamp: new Date(),
        },
      },
    },
  });
}

app.listen(3000, () => {
  console.log("CC Relay Server with x402 running on port 3000");
});
```

### 3.3 智能合约集成

```solidity
// contracts/CCRelayPayment.sol

// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "@openzeppelin/contracts/token/ERC20/IERC20.sol";

/**
 * CC 中转站支付合约
 * 与 x402 协议配合使用
 */
contract CCRelayPayment {
    IERC20 public immutable usdc;
    address public relayWallet;

    struct CreditRecord {
        uint256 balance;        // 用户额度余额（USDC，6 位小数）
        uint256 totalRecharged; // 总充值金额
        uint256 totalSpent;     // 总消费金额
    }

    mapping(address => CreditRecord) public userCredits;

    event CreditRecharged(address indexed user, uint256 amount, bytes32 txId);
    event CreditUsed(address indexed user, uint256 amount, string service);

    constructor(address _usdc, address _relayWallet) {
        usdc = IERC20(_usdc);
        relayWallet = _relayWallet;
    }

    /**
     * 用户充值额度
     * x402 协议会先完成 USDC 转账，然后调用此函数记录
     */
    function recordRecharge(
        address user,
        uint256 amount,
        bytes32 txId
    ) external {
        require(msg.sender == relayWallet, "Only relay");

        userCredits[user].balance += amount;
        userCredits[user].totalRecharged += amount;

        emit CreditRecharged(user, amount, txId);
    }

    /**
     * 消费额度调用 CC 服务
     */
    function recordUsage(
        address user,
        uint256 amount,
        string calldata service
    ) external {
        require(msg.sender == relayWallet, "Only relay");
        require(userCredits[user].balance >= amount, "Insufficient credits");

        userCredits[user].balance -= amount;
        userCredits[user].totalSpent += amount;

        emit CreditUsed(user, amount, service);
    }

    /**
     * 查询用户额度
     */
    function getCredits(address user) external view returns (uint256) {
        return userCredits[user].balance;
    }

    /**
     * 查询用户统计信息
     */
    function getUserStats(address user) external view returns (
        uint256 balance,
        uint256 totalRecharged,
        uint256 totalSpent
    ) {
        CreditRecord memory record = userCredits[user];
        return (record.balance, record.totalRecharged, record.totalSpent);
    }
}
```

## 四、x402 的展示形式

### 4.1 用户界面展示

#### 4.1.1 充值页面

```tsx
// relay_ui/src/components/RechargePanel.tsx

import { useState } from "react";
import { useWallet } from "@thirdweb-dev/react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card } from "@/components/ui/card";

export function RechargePanel() {
  const [amount, setAmount] = useState("");
  const [loading, setLoading] = useState(false);
  const wallet = useWallet();

  const handleRecharge = async () => {
    setLoading(true);
    try {
      // 调用 MCP 工具的充值函数
      const result = await window.mcpTool.rechargeCredits(amount);

      alert(`充值成功！交易哈希: ${result.txHash}`);
    } catch (error) {
      alert("充值失败: " + error.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <Card className="p-6">
      <h2 className="text-2xl font-bold mb-4">充值 CC 额度</h2>

      <div className="space-y-4">
        <div>
          <label className="text-sm font-medium">充值金额 (USDC)</label>
          <Input
            type="number"
            step="0.01"
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
            placeholder="输入 USDC 金额"
          />
        </div>

        <Button
          onClick={handleRecharge}
          disabled={loading || !amount}
          className="w-full"
        >
          {loading ? "处理中..." : "使用 x402 支付充值"}
        </Button>

        <div className="bg-blue-50 p-4 rounded-lg text-sm">
          <p className="font-semibold mb-2">x402 支付流程：</p>
          <ol className="list-decimal list-inside space-y-1">
            <li>点击按钮后，钱包将自动弹出</li>
            <li>确认支付 USDC 到中转站</li>
            <li>无需持有 MON 代币作为 Gas</li>
            <li>支付在 2 秒内完成</li>
            <li>额度立即到账，可在区块链上验证</li>
          </ol>
        </div>
      </div>
    </Card>
  );
}
```

#### 4.1.2 支付历史记录

```tsx
// relay_ui/src/components/PaymentHistory.tsx

import { useEffect, useState } from "react";
import { Table } from "@/components/ui/table";

export function PaymentHistory() {
  const [transactions, setTransactions] = useState([]);

  useEffect(() => {
    // 从中转站后台获取支付历史
    fetchPaymentHistory();
  }, []);

  return (
    <div>
      <h2 className="text-2xl font-bold mb-4">x402 支付历史</h2>

      <Table>
        <thead>
          <tr>
            <th>时间</th>
            <th>类型</th>
            <th>金额 (USDC)</th>
            <th>服务</th>
            <th>交易哈希</th>
            <th>状态</th>
          </tr>
        </thead>
        <tbody>
          {transactions.map((tx) => (
            <tr key={tx.txHash}>
              <td>{new Date(tx.timestamp).toLocaleString()}</td>
              <td>
                {tx.type === "recharge" ? (
                  <span className="text-green-600">充值</span>
                ) : (
                  <span className="text-blue-600">消费</span>
                )}
              </td>
              <td>{tx.amount}</td>
              <td>{tx.service || "-"}</td>
              <td>
                <a
                  href={`https://testnet.monadexplorer.com/tx/${tx.txHash}`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-blue-600 hover:underline"
                >
                  {tx.txHash.slice(0, 10)}...
                </a>
              </td>
              <td>
                <span className="text-green-600">✓ 已确认</span>
              </td>
            </tr>
          ))}
        </tbody>
      </Table>

      <div className="mt-4 p-4 bg-gray-50 rounded-lg">
        <p className="text-sm text-gray-600">
          💡 所有支付均通过 <strong>x402 协议</strong> 在 Monad 测试网上完成，
          交易数据完全公开透明，可在区块浏览器上验证。
        </p>
      </div>
    </div>
  );
}
```

#### 4.1.3 额度统计仪表板

```tsx
// relay_ui/src/components/CreditsDashboard.tsx

import { useEffect, useState } from "react";
import { Card } from "@/components/ui/card";
import { BarChart, Bar, XAxis, YAxis, Tooltip } from "recharts";

export function CreditsDashboard() {
  const [stats, setStats] = useState({
    balance: 0,
    totalRecharged: 0,
    totalSpent: 0,
    transactions: [],
  });

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-3 gap-4">
        <Card className="p-6">
          <h3 className="text-sm text-gray-600">当前余额</h3>
          <p className="text-3xl font-bold text-blue-600">
            {stats.balance} USDC
          </p>
        </Card>

        <Card className="p-6">
          <h3 className="text-sm text-gray-600">累计充值</h3>
          <p className="text-3xl font-bold text-green-600">
            {stats.totalRecharged} USDC
          </p>
        </Card>

        <Card className="p-6">
          <h3 className="text-sm text-gray-600">累计消费</h3>
          <p className="text-3xl font-bold text-orange-600">
            {stats.totalSpent} USDC
          </p>
        </Card>
      </div>

      <Card className="p-6">
        <h3 className="text-lg font-semibold mb-4">x402 支付统计</h3>
        <BarChart width={600} height={300} data={stats.transactions}>
          <XAxis dataKey="date" />
          <YAxis />
          <Tooltip />
          <Bar dataKey="amount" fill="#3b82f6" />
        </BarChart>
      </Card>

      <Card className="p-6 bg-gradient-to-r from-blue-50 to-purple-50">
        <h3 className="text-lg font-semibold mb-2">
          🚀 x402 协议优势
        </h3>
        <ul className="space-y-2 text-sm">
          <li>✅ <strong>即时支付</strong>：2 秒内完成链上结算</li>
          <li>✅ <strong>零手续费</strong>：协议本身不收取任何费用</li>
          <li>✅ <strong>无需 Gas</strong>：Facilitator 代付交易费用</li>
          <li>✅ <strong>自动重试</strong>：RPC 失败自动切换节点</li>
          <li>✅ <strong>透明可追溯</strong>：所有交易记录在区块链上</li>
        </ul>
      </Card>
    </div>
  );
}
```

### 4.2 MCP 工具中的 x402 体现

```typescript
// mcp_tool/src/index.ts

import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { callCCServiceWithPayment, rechargeCredits } from "./x402-client.js";

const server = new Server({
  name: "cc-relay-x402-mcp",
  version: "1.0.0",
}, {
  capabilities: {
    tools: {},
  },
});

// 注册 MCP 工具：调用 CC 服务
server.setRequestHandler("tools/list", async () => ({
  tools: [
    {
      name: "call_cc_service",
      description: "使用 x402 协议支付并调用 CC 大模型服务",
      inputSchema: {
        type: "object",
        properties: {
          model: {
            type: "string",
            description: "CC 模型名称（如 claude-3-sonnet）",
          },
          prompt: {
            type: "string",
            description: "输入提示词",
          },
        },
        required: ["model", "prompt"],
      },
    },
    {
      name: "recharge_credits",
      description: "通过 x402 协议充值 CC 使用额度",
      inputSchema: {
        type: "object",
        properties: {
          amount: {
            type: "string",
            description: "充值金额（USDC）",
          },
        },
        required: ["amount"],
      },
    },
  ],
}));

// 处理工具调用
server.setRequestHandler("tools/call", async (request) => {
  const { name, arguments: args } = request.params;

  if (name === "call_cc_service") {
    const result = await callCCServiceWithPayment(
      `${CC_RELAY_URL}/api/cc/${args.model}`,
      userWallet
    );

    return {
      content: [
        {
          type: "text",
          text: `✅ x402 支付成功！\n模型响应: ${result.data}\n交易哈希: ${result.txHash}\n费用: ${result.cost} USDC`,
        },
      ],
    };
  }

  if (name === "recharge_credits") {
    const result = await rechargeCredits(args.amount, userWallet);

    return {
      content: [
        {
          type: "text",
          text: `✅ 充值成功！\n金额: ${args.amount} USDC\n交易哈希: ${result.txHash}\n新余额: ${result.newBalance} USDC`,
        },
      ],
    };
  }
});

const transport = new StdioServerTransport();
await server.connect(transport);
```

## 五、项目中 x402 的可视化展示

### 5.1 流程图展示

在项目演示时，可以通过以下流程图展示 x402：

```
用户操作流程：
┌──────────┐
│ 用户钱包  │ (MetaMask / Coinbase Wallet)
└────┬─────┘
     │ 1. 连接钱包
┌────▼──────────────────┐
│  MCP 工具 (x402 客户端) │
│  - wrapFetchWithPayment │
└────┬──────────────────┘
     │ 2. HTTP 请求 CC 服务
┌────▼──────────────────┐
│  中转站后台            │
│  返回 402 + 支付要求   │
└────┬──────────────────┘
     │ 3. MCP 自动签名交易
┌────▼──────────────────┐
│  Thirdweb Facilitator  │
│  - 处理 USDC 支付      │
│  - 无需 Gas Token      │
└────┬──────────────────┘
     │ 4. 上链确认
┌────▼──────────────────┐
│    Monad 测试网        │
│  - 2 秒内确认          │
│  - 记录到区块链        │
└────┬──────────────────┘
     │ 5. 支付成功
┌────▼──────────────────┐
│  中转站返回 CC 响应    │
│  - 模型输出            │
│  - 交易哈希            │
│  - 费用统计            │
└───────────────────────┘
```

### 5.2 实时状态展示

在 UI 中实时展示 x402 支付过程：

```tsx
export function PaymentStatusIndicator() {
  const [status, setStatus] = useState("idle");

  // 状态: idle → requesting → paying → confirming → completed

  return (
    <div className="flex items-center space-x-4">
      <div className={`step ${status === "requesting" ? "active" : ""}`}>
        1. 请求服务
      </div>
      <div className={`step ${status === "paying" ? "active" : ""}`}>
        2. x402 支付
      </div>
      <div className={`step ${status === "confirming" ? "active" : ""}`}>
        3. 链上确认
      </div>
      <div className={`step ${status === "completed" ? "active" : ""}`}>
        4. 服务响应
      </div>
    </div>
  );
}
```

### 5.3 技术演示要点

在黑客松演示时，重点展示以下 x402 特性：

| 演示环节 | 展示内容 | 技术亮点 |
|---------|---------|---------|
| **1. 充值演示** | 用户点击充值 → 钱包弹窗 → 确认支付 → 2 秒到账 | x402 的即时支付 |
| **2. 服务调用** | MCP 工具调用 CC 服务 → 自动扣费 → 返回结果 | x402 的无缝集成 |
| **3. 支付历史** | 显示所有交易记录，点击查看链上哈希 | x402 的透明性 |
| **4. 失败重试** | 模拟 RPC 失败 → 自动切换节点 → 支付成功 | x402 的可靠性 |
| **5. 幂等性演示** | 重复点击充值 → 只扣一次款 | x402 的安全性 |

## 六、技术优势总结

### 6.1 x402 解决的核心问题

| 传统方案 | x402 方案 | 优势 |
|---------|----------|------|
| 需要账户系统和 API Key | 无需注册，钱包即身份 | 降低接入门槛 |
| 订阅制或预付费 | 按使用付费，实时结算 | 更灵活 |
| 中心化支付平台（手续费高） | 去中心化，零手续费 | 成本更低 |
| 人工对账和结算 | 自动化，链上可验证 | 透明可信 |
| 不支持机器自主支付 | AI Agent 可自动调用 | 适合 Agent 经济 |

### 6.2 Monad + x402 的协同效应

**Monad 测试网特性：**
- 10,000 TPS 高吞吐量
- 0.4 秒超快出块
- 单槽最终性（Single-slot finality）
- 极低 Gas 费用

**x402 协议特性：**
- HTTP 原生集成
- 支持 USDC 支付
- Facilitator 代付 Gas
- 自动重试机制

**结合后的优势：**
✅ **真正的即时支付**：Monad 的快速出块 + x402 的流程简化 = 2 秒完成支付
✅ **支持小额支付**：Monad 低费用 + x402 零协议费 = 适合 0.001 USDC 级别的微支付
✅ **高并发处理**：Monad 10,000 TPS + x402 并行处理 = 支持大量 AI Agent 同时调用
✅ **用户体验优化**：Facilitator 代付 Gas + Monad 快速确认 = 用户无需持有 MON 代币

## 七、项目实施建议

### 7.1 开发优先级

**P0 - 核心功能（必须完成）：**
1. ✅ 集成 Thirdweb x402 SDK
2. ✅ 实现充值功能（MCP 工具 + 后台）
3. ✅ 实现服务调用和扣费
4. ✅ 基础 UI（充值页面 + 额度显示）

**P1 - 重要功能（优先完成）：**
5. ✅ 支付历史记录
6. ✅ 额度统计仪表板
7. ✅ 区块链浏览器链接

**P2 - 增强功能（时间允许）：**
8. 实时支付状态展示
9. 失败重试演示
10. 幂等性测试

### 7.2 技术栈选择

```
前端 (中转站 UI):
- Next.js 14
- Thirdweb React SDK
- shadcn/ui
- Recharts (图表)

后端 (中转站后台):
- Express.js
- Thirdweb Node.js SDK
- PostgreSQL (额度管理)
- Prisma ORM

MCP 工具:
- @modelcontextprotocol/sdk
- Thirdweb SDK
- viem

区块链:
- Monad 测试网
- Thirdweb Facilitator
- USDC (Circle)
```

### 7.3 10 小时开发计划

| 时间 | 任务 | 产出 |
|-----|------|------|
| 0-1h | 项目搭建 + Thirdweb 配置 | 环境就绪 |
| 1-2h | x402 后台集成 | 支付验证可用 |
| 2-3h | MCP 工具 x402 客户端 | 工具可调用 |
| 3-4h | 充值功能开发 | 充值流程完整 |
| 4-5h | 服务调用和扣费 | 核心功能完成 |
| 5-6h | 支付历史 UI | 记录可查询 |
| 6-7h | 额度统计仪表板 | 数据可视化 |
| 7-8h | 测试和调试 | 流程稳定 |
| 8-9h | UI 优化和动画 | 体验提升 |
| 9-10h | 演示准备和视频录制 | Demo 就绪 |

## 八、参考资源

**官方文档：**
- x402 协议白皮书: https://www.x402.org/x402-whitepaper.pdf
- Thirdweb x402 文档: https://portal.thirdweb.com/typescript/v5/x402
- Monad x402 教程: https://monad-foundation.notion.site/Monad-x402-2ae6367594f28194bed7dd46c2741c48

**示例代码：**
- Thirdweb x402 示例: https://github.com/thirdweb-dev/js/tree/main/packages/thirdweb/src/x402
- Monad x402 示例项目: (参见 Monad 文档)

**工具和资源：**
- Monad 测试网 Faucet: https://testnet.monad.xyz
- USDC Faucet: https://faucet.circle.com/
- Monad 区块浏览器: https://testnet.monadexplorer.com/

---

**文档版本**: v1.0
**创建时间**: 2025-11-29
**状态**: ✅ 技术风险已解决
