# Claude Relay Service 技术分析文档

> 本文档详细分析 claude-relay-service 项目的 Claude 模型调用代理实现和 Token 消耗计算逻辑，用于 Python 复刻开发参考。

## 目录

1. [项目架构概览](#项目架构概览)
2. [Claude 模型调用代理实现](#claude-模型调用代理实现)
3. [Token 消耗计算逻辑](#token-消耗计算逻辑)
4. [Python 复刻开发建议](#python-复刻开发建议)

---

## 项目架构概览

### 核心技术栈

- **运行环境**: Node.js (>=18.0.0)
- **Web框架**: Express.js
- **数据存储**: Redis (IORedis)
- **HTTP请求**: Node.js 原生 HTTPS 模块
- **代理支持**: socks-proxy-agent, https-proxy-agent
- **日志系统**: Winston
- **加密**: Node.js crypto (AES加密、SHA256哈希)

### 项目目录结构

```
claude-relay-service/
├── src/
│   ├── app.js                    # 应用主入口
│   ├── routes/                   # 路由层
│   │   ├── api.js                # Claude API 路由
│   │   ├── geminiRoutes.js       # Gemini API 路由
│   │   ├── openaiRoutes.js       # OpenAI 兼容路由
│   │   └── admin/                # 管理接口
│   ├── services/                 # 业务逻辑层
│   │   ├── claudeRelayService.js           # Claude 代理服务
│   │   ├── claudeAccountService.js         # Claude 账户管理
│   │   ├── unifiedClaudeScheduler.js       # 统一调度器
│   │   ├── apiKeyService.js                # API Key 管理
│   │   ├── pricingService.js               # 定价服务
│   │   └── ...                             # 其他服务
│   ├── middleware/               # 中间件
│   │   └── auth.js               # API Key 认证中间件
│   ├── utils/                    # 工具函数
│   │   ├── proxyHelper.js        # 代理工具
│   │   ├── sessionHelper.js      # 会话管理
│   │   ├── rateLimitHelper.js    # 速率限制
│   │   └── logger.js             # 日志工具
│   └── models/
│       └── redis.js              # Redis 数据模型
├── config/
│   └── config.js                 # 配置文件
└── data/
    └── model_pricing.json        # 模型定价数据
```

### 核心流程图

```
客户端请求
    ↓
authenticateApiKey 中间件 (API Key 验证、权限检查、速率限制)
    ↓
unifiedClaudeScheduler (选择可用账户、会话绑定)
    ↓
claudeRelayService (获取 token、设置代理、转发请求)
    ↓
Claude API (Anthropic)
    ↓
响应处理 (流式/非流式)
    ↓
Usage 捕获 (解析 token 使用量)
    ↓
成本计算 (pricingService)
    ↓
更新统计 (Redis)
    ↓
返回客户端
```

---

## Claude 模型调用代理实现

### 1. API Key 认证流程

#### 核心代码位置
- 文件: `src/middleware/auth.js`
- 方法: `authenticateApiKey`

#### 认证步骤

```javascript
// 1. 从请求头提取 API Key
const authHeader = req.headers.authorization
// 格式: "Bearer cr_xxxxxx"

// 2. 计算 API Key 哈希
const keyHash = crypto.createHash('sha256')
  .update(apiKey + encryptionKey)
  .digest('hex')

// 3. 从 Redis 查询 API Key 数据
const apiKeyData = await redis.get(`api_key_hash:${keyHash}`)

// 4. 验证检查
// - API Key 是否存在
// - 是否已删除
// - 是否过期
// - 配额是否用尽
// - 速率限制是否超限

// 5. 权限检查
// - 服务权限 (all/claude/gemini/openai)
// - 客户端限制 (基于 User-Agent)
// - 模型黑名单检查

// 6. 将 API Key 数据附加到请求对象
req.apiKey = apiKeyData
```

#### Redis 数据结构

```javascript
// API Key 数据
{
  id: "key_123",
  name: "My API Key",
  keyHash: "sha256_hash",
  userId: "user_456",
  permissions: "all", // all/claude/gemini/openai
  enableModelRestriction: true,
  restrictedModels: ["claude-opus-4"],
  enableClientRestriction: true,
  allowedClients: ["claude-code"],
  limit: 1000000, // token 限额
  expiresAt: 1234567890,
  createdAt: 1234567890
}
```

### 2. 账户选择调度

#### 核心代码位置
- 文件: `src/services/unifiedClaudeScheduler.js`
- 方法: `selectAccountForApiKey`

#### 调度逻辑

```javascript
async selectAccountForApiKey(apiKeyData, sessionHash, requestedModel) {
  // 1. 解析模型前缀 (例如: "ccr/claude-sonnet-4")
  const { vendor, baseModel } = parseVendorPrefixedModel(requestedModel)

  // 2. 检查专属账户绑定
  if (apiKeyData.claudeAccountId) {
    // 如果是账户组 (group:xxx)
    if (apiKeyData.claudeAccountId.startsWith('group:')) {
      return await this._selectFromGroup(groupId, sessionHash, requestedModel)
    }
    // 专属单个账户
    return { accountId: apiKeyData.claudeAccountId, accountType: 'claude-official' }
  }

  // 3. 检查会话粘性 (Sticky Session)
  const sessionKey = `unified_claude_session_mapping:${sessionHash}`
  const cachedBinding = await redis.get(sessionKey)
  if (cachedBinding) {
    // 验证账户是否仍然可用
    const account = await this._getAccountByType(cachedBinding.accountId, cachedBinding.accountType)
    if (this._isAccountUsable(account)) {
      return cachedBinding
    }
  }

  // 4. 从所有可用账户中选择
  const candidates = await this._getAvailableAccounts(requestedModel)

  // 5. 过滤条件
  // - status === 'active'
  // - schedulable !== false
  // - 支持请求的模型
  // - 未被限流
  // - 未被标记为过载 (529错误)
  // - 并发数未满

  // 6. 选择策略: 轮询 (Round-Robin)
  const selected = candidates[index % candidates.length]

  // 7. 保存会话绑定 (TTL: 1小时)
  if (sessionHash) {
    await redis.setex(sessionKey, 3600, JSON.stringify({
      accountId: selected.id,
      accountType: selected.type
    }))
  }

  return { accountId: selected.id, accountType: selected.type }
}
```

#### 支持的账户类型

| 账户类型 | 说明 | 认证方式 |
|---------|------|---------|
| claude-official | Claude 官方 OAuth 账户 | OAuth 2.0 Bearer Token |
| claude-console | Claude Console 账户 | Session Key |
| bedrock | AWS Bedrock | AWS Credentials |
| ccr | CCR 凭据 | API Key |
| azure-openai | Azure OpenAI | Azure API Key |
| gemini | Google Gemini | Google OAuth |
| openai-responses | OpenAI Responses (Codex) | API Key |
| droid | Droid (Factory.ai) | API Key |

### 3. Token 管理

#### OAuth Token 刷新机制

```javascript
// 文件: src/services/claudeAccountService.js
async getValidAccessToken(accountId) {
  const account = await this.getAccount(accountId)

  // 1. 解密 OAuth 数据
  const decrypted = this._decryptData(account.claudeAiOauthEncrypted)
  const { accessToken, refreshToken, expiresAt } = decrypted

  // 2. 检查是否需要刷新 (提前10秒刷新)
  const now = Math.floor(Date.now() / 1000)
  if (now >= expiresAt - 10) {
    // 3. 刷新 Token
    const newTokens = await this._refreshOAuthToken(refreshToken, account.proxyConfig)

    // 4. 加密并保存
    await this._updateTokens(accountId, newTokens)

    return newTokens.accessToken
  }

  return accessToken
}

async _refreshOAuthToken(refreshToken, proxyConfig) {
  const agent = this._getProxyAgent(proxyConfig)

  const response = await axios.post('https://api.claude.ai/api/oauth/token', {
    grant_type: 'refresh_token',
    refresh_token: refreshToken
  }, {
    httpsAgent: agent,
    headers: {
      'Content-Type': 'application/json'
    }
  })

  return {
    accessToken: response.data.access_token,
    refreshToken: response.data.refresh_token,
    expiresAt: Math.floor(Date.now() / 1000) + response.data.expires_in
  }
}
```

#### 数据加密存储

```javascript
// AES-256-CBC 加密
function encryptData(data, encryptionKey) {
  const iv = crypto.randomBytes(16)
  const cipher = crypto.createCipheriv('aes-256-cbc', Buffer.from(encryptionKey, 'hex'), iv)

  let encrypted = cipher.update(JSON.stringify(data), 'utf8', 'hex')
  encrypted += cipher.final('hex')

  return iv.toString('hex') + ':' + encrypted
}

function decryptData(encryptedData, encryptionKey) {
  const [ivHex, encryptedHex] = encryptedData.split(':')
  const iv = Buffer.from(ivHex, 'hex')
  const decipher = crypto.createDecipheriv('aes-256-cbc', Buffer.from(encryptionKey, 'hex'), iv)

  let decrypted = decipher.update(encryptedHex, 'hex', 'utf8')
  decrypted += decipher.final('utf8')

  return JSON.parse(decrypted)
}
```

### 4. 代理请求转发

#### 核心代码位置
- 文件: `src/services/claudeRelayService.js`
- 方法: `relayRequest`, `relayStreamRequestWithUsageCapture`

#### 非流式请求

```javascript
async relayRequest(requestBody, apiKeyData, clientRequest, clientResponse, clientHeaders, options = {}) {
  // 1. 选择账户
  const sessionHash = sessionHelper.generateSessionHash(requestBody)
  const { accountId, accountType } = await unifiedClaudeScheduler.selectAccountForApiKey(
    apiKeyData,
    sessionHash,
    requestBody.model
  )

  // 2. 获取访问 Token
  const accessToken = await claudeAccountService.getValidAccessToken(accountId)

  // 3. 处理请求体
  const processedBody = this._processRequestBody(requestBody, account)
  // - 添加 Claude Code 系统提示词
  // - 验证和限制 max_tokens
  // - 移除 cache_control 中的 ttl 字段
  // - 处理统一客户端标识

  // 4. 获取代理配置
  const proxyAgent = await this._getProxyAgent(accountId)

  // 5. 发送 HTTPS 请求
  const response = await this._makeClaudeRequest(
    processedBody,
    accessToken,
    proxyAgent,
    clientHeaders,
    accountId,
    options
  )

  return response
}

async _makeClaudeRequest(requestPayload, accessToken, proxyAgent, clientHeaders, accountId, options) {
  return new Promise((resolve, reject) => {
    const requestOptions = {
      hostname: 'api.claude.ai',
      path: '/api/v1/messages',
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${accessToken}`,
        'anthropic-version': '2023-06-01',
        'anthropic-beta': this._getBetaHeader(requestPayload.model, clientHeaders['anthropic-beta']),
        'x-api-key': accessToken
      },
      agent: proxyAgent,
      timeout: config.requestTimeout || 600000 // 默认 10 分钟
    }

    const req = https.request(requestOptions, (res) => {
      let responseData = []

      res.on('data', (chunk) => {
        responseData.push(chunk)
      })

      res.on('end', () => {
        const body = Buffer.concat(responseData)

        // 处理 gzip 压缩
        if (res.headers['content-encoding'] === 'gzip') {
          zlib.gunzip(body, (err, decoded) => {
            if (err) {
              reject(err)
            } else {
              resolve({
                statusCode: res.statusCode,
                headers: res.headers,
                body: decoded.toString()
              })
            }
          })
        } else {
          resolve({
            statusCode: res.statusCode,
            headers: res.headers,
            body: body.toString()
          })
        }
      })
    })

    req.on('error', (error) => {
      reject(error)
    })

    req.write(JSON.stringify(requestPayload))
    req.end()
  })
}
```

#### 流式请求 (SSE)

```javascript
async relayStreamRequestWithUsageCapture(
  requestBody,
  apiKeyData,
  responseStream,
  clientHeaders,
  usageCallback,
  streamTransformer = null,
  options = {}
) {
  // ... 选择账户和获取 Token (同上)

  return new Promise((resolve, reject) => {
    const req = https.request(requestOptions, (res) => {
      // 设置 SSE 响应头
      if (!responseStream.headersSent) {
        responseStream.setHeader('Content-Type', 'text/event-stream')
        responseStream.setHeader('Cache-Control', 'no-cache')
        responseStream.setHeader('Connection', 'keep-alive')
        responseStream.setHeader('X-Accel-Buffering', 'no') // 禁用 Nginx 缓冲
      }

      // 禁用 Nagle 算法,确保数据立即发送
      if (responseStream.socket) {
        responseStream.socket.setNoDelay(true)
      }

      let buffer = ''
      const allUsageData = []
      let currentUsageData = {}

      res.on('data', (chunk) => {
        try {
          buffer += chunk.toString()
          const lines = buffer.split('\n')
          buffer = lines.pop() || '' // 保留不完整行

          // 转发数据到客户端
          if (lines.length > 0 && !responseStream.destroyed) {
            const linesToForward = lines.join('\n') + '\n'
            if (streamTransformer) {
              const transformed = streamTransformer(linesToForward)
              if (transformed) {
                responseStream.write(transformed)
              }
            } else {
              responseStream.write(linesToForward)
            }
          }

          // 解析 SSE 事件捕获 Usage
          for (const line of lines) {
            if (line.startsWith('data:')) {
              const jsonStr = line.slice(5).trimStart()
              if (!jsonStr || jsonStr === '[DONE]') continue

              try {
                const data = JSON.parse(jsonStr)

                // message_start: 包含输入 tokens 和缓存 tokens
                if (data.type === 'message_start' && data.message?.usage) {
                  currentUsageData.input_tokens = data.message.usage.input_tokens || 0
                  currentUsageData.cache_creation_input_tokens =
                    data.message.usage.cache_creation_input_tokens || 0
                  currentUsageData.cache_read_input_tokens =
                    data.message.usage.cache_read_input_tokens || 0
                  currentUsageData.model = data.message.model

                  // 捕获详细的缓存创建数据
                  if (data.message.usage.cache_creation &&
                      typeof data.message.usage.cache_creation === 'object') {
                    currentUsageData.cache_creation = {
                      ephemeral_5m_input_tokens:
                        data.message.usage.cache_creation.ephemeral_5m_input_tokens || 0,
                      ephemeral_1h_input_tokens:
                        data.message.usage.cache_creation.ephemeral_1h_input_tokens || 0
                    }
                  }
                }

                // message_delta: 包含输出 tokens
                if (data.type === 'message_delta' && data.usage?.output_tokens !== undefined) {
                  currentUsageData.output_tokens = data.usage.output_tokens || 0

                  // 数据完整,保存
                  if (currentUsageData.input_tokens !== undefined) {
                    allUsageData.push({ ...currentUsageData })
                    currentUsageData = {}
                  }
                }
              } catch (parseError) {
                // 忽略 JSON 解析错误
              }
            }
          }
        } catch (error) {
          logger.error('Error processing stream data:', error)
        }
      })

      res.on('end', async () => {
        // 流结束,触发 Usage 回调
        if (allUsageData.length > 0 && usageCallback) {
          await usageCallback(allUsageData, accountId, accountType)
        }

        if (!responseStream.destroyed) {
          responseStream.end()
        }

        resolve()
      })
    })

    req.on('error', reject)
    req.write(JSON.stringify(processedBody))
    req.end()
  })
}
```

#### Beta Header 处理

```javascript
_getBetaHeader(modelId, clientBetaHeader) {
  const OAUTH_BETA = 'oauth-2025-04-20'
  const CLAUDE_CODE_BETA = 'claude-code-20250219'

  // 客户端传递了 beta header
  if (clientBetaHeader) {
    // 已包含 oauth beta
    if (clientBetaHeader.includes(OAUTH_BETA)) {
      return clientBetaHeader
    }

    // 添加 oauth beta
    const parts = clientBetaHeader.split(',').map(p => p.trim())
    const claudeCodeIndex = parts.findIndex(p => p === CLAUDE_CODE_BETA)

    if (claudeCodeIndex !== -1) {
      parts.splice(claudeCodeIndex + 1, 0, OAUTH_BETA)
    } else {
      parts.unshift(OAUTH_BETA)
    }

    return parts.join(',')
  }

  // 根据模型判断
  const isHaikuModel = modelId?.toLowerCase().includes('haiku')
  if (isHaikuModel) {
    return 'oauth-2025-04-20,interleaved-thinking-2025-05-14'
  }

  return 'claude-code-20250219,oauth-2025-04-20,interleaved-thinking-2025-05-14,fine-grained-tool-streaming-2025-05-14'
}
```

### 5. 代理配置

#### 代理类型支持

```javascript
// 文件: src/utils/proxyHelper.js
class ProxyHelper {
  static createProxyAgent(proxyConfig) {
    if (!proxyConfig || !proxyConfig.enabled) {
      return null
    }

    const { protocol, host, port, username, password } = proxyConfig

    // SOCKS5 代理
    if (protocol === 'socks5') {
      const SocksProxyAgent = require('socks-proxy-agent').SocksProxyAgent
      const proxyUrl = username
        ? `socks5://${username}:${password}@${host}:${port}`
        : `socks5://${host}:${port}`

      return new SocksProxyAgent(proxyUrl, {
        timeout: 30000,
        family: 4 // 强制使用 IPv4
      })
    }

    // HTTP/HTTPS 代理
    if (protocol === 'http' || protocol === 'https') {
      const HttpsProxyAgent = require('https-proxy-agent').HttpsProxyAgent
      const proxyUrl = username
        ? `${protocol}://${username}:${password}@${host}:${port}`
        : `${protocol}://${host}:${port}`

      return new HttpsProxyAgent(proxyUrl, {
        timeout: 30000
      })
    }

    return null
  }
}
```

#### 账户代理配置示例

```javascript
{
  id: "account_123",
  name: "My Claude Account",
  proxyEnabled: true,
  proxyProtocol: "socks5",
  proxyHost: "127.0.0.1",
  proxyPort: 1080,
  proxyUsername: "user",
  proxyPassword: "pass"
}
```

---

## Token 消耗计算逻辑

### 1. Usage 数据结构

#### Claude API 返回的 Usage 格式

```javascript
// 非流式响应
{
  "usage": {
    "input_tokens": 1024,
    "output_tokens": 512,
    "cache_creation_input_tokens": 2048,
    "cache_read_input_tokens": 256,
    // 新格式: 详细的缓存创建数据
    "cache_creation": {
      "ephemeral_5m_input_tokens": 1024,
      "ephemeral_1h_input_tokens": 1024
    }
  }
}

// 流式响应 (SSE 事件)
// 事件 1: message_start
data: {
  "type": "message_start",
  "message": {
    "id": "msg_xxx",
    "model": "claude-sonnet-4-20250514",
    "usage": {
      "input_tokens": 1024,
      "cache_creation_input_tokens": 2048,
      "cache_read_input_tokens": 256,
      "cache_creation": {
        "ephemeral_5m_input_tokens": 1024,
        "ephemeral_1h_input_tokens": 1024
      }
    }
  }
}

// 事件 2: message_delta
data: {
  "type": "message_delta",
  "usage": {
    "output_tokens": 512
  }
}
```

### 2. 定价服务 (PricingService)

#### 定价数据加载

```javascript
// 文件: src/services/pricingService.js
class PricingService {
  constructor() {
    this.pricingFile = path.join(process.cwd(), 'data', 'model_pricing.json')
    this.pricingData = null
    this.updateInterval = 24 * 60 * 60 * 1000 // 24小时
  }

  async initialize() {
    // 1. 从远程下载最新定价数据
    await this.downloadPricingData()

    // 2. 加载到内存
    this.pricingData = JSON.parse(fs.readFileSync(this.pricingFile, 'utf8'))

    // 3. 设置定时更新
    setInterval(() => this.checkAndUpdatePricing(), this.updateInterval)
  }

  async downloadPricingData() {
    const response = await https.get(this.pricingUrl)
    fs.writeFileSync(this.pricingFile, JSON.stringify(response.data, null, 2))
  }

  getModelPricing(modelName) {
    if (!this.pricingData) {
      return null
    }

    const pricing = this.pricingData[modelName]
    if (!pricing) {
      return null
    }

    // 确保缓存价格存在
    return this.ensureCachePricing(pricing)
  }

  ensureCachePricing(pricing) {
    // 如果缺少缓存价格,根据输入价格计算
    if (!pricing.cache_creation_input_token_cost && pricing.input_cost_per_token) {
      // 缓存创建价格 = 输入价格 × 1.25
      pricing.cache_creation_input_token_cost = pricing.input_cost_per_token * 1.25
    }
    if (!pricing.cache_read_input_token_cost && pricing.input_cost_per_token) {
      // 缓存读取价格 = 输入价格 × 0.1
      pricing.cache_read_input_token_cost = pricing.input_cost_per_token * 0.1
    }
    return pricing
  }
}
```

#### 模型定价数据格式

```json
{
  "claude-sonnet-4-20250514": {
    "input_cost_per_token": 0.000003,
    "output_cost_per_token": 0.000015,
    "cache_creation_input_token_cost": 0.00000375,
    "cache_read_input_token_cost": 0.0000003,
    "max_tokens": 8192,
    "max_context_window": 200000
  },
  "claude-opus-4-20250514": {
    "input_cost_per_token": 0.000015,
    "output_cost_per_token": 0.000075,
    "cache_creation_input_token_cost": 0.00001875,
    "cache_read_input_token_cost": 0.0000015,
    "max_tokens": 8192,
    "max_context_window": 200000
  }
}
```

### 3. 成本计算算法

#### 核心计算方法

```javascript
calculateCost(usage, modelName) {
  // 1. 检查是否为 1M 上下文模型
  const isLongContextModel = modelName?.includes('[1m]')
  let useLongContextPricing = false

  if (isLongContextModel) {
    const totalInputTokens =
      (usage.input_tokens || 0) +
      (usage.cache_creation_input_tokens || 0) +
      (usage.cache_read_input_tokens || 0)

    // 超过 200k tokens 使用 1M 上下文价格
    if (totalInputTokens > 200000) {
      useLongContextPricing = true
    }
  }

  // 2. 获取模型定价
  const pricing = this.getModelPricing(modelName)

  if (!pricing && !useLongContextPricing) {
    return {
      inputCost: 0,
      outputCost: 0,
      cacheCreateCost: 0,
      cacheReadCost: 0,
      totalCost: 0,
      hasPricing: false
    }
  }

  // 3. 计算基础成本
  let inputCost = 0
  let outputCost = 0

  if (useLongContextPricing) {
    // 使用 1M 上下文特殊价格
    const longContextPrices = this.longContextPricing[modelName]
    inputCost = (usage.input_tokens || 0) * longContextPrices.input
    outputCost = (usage.output_tokens || 0) * longContextPrices.output
  } else {
    // 使用标准价格
    inputCost = (usage.input_tokens || 0) * pricing.input_cost_per_token
    outputCost = (usage.output_tokens || 0) * pricing.output_cost_per_token
  }

  // 4. 计算缓存读取成本
  const cacheReadCost =
    (usage.cache_read_input_tokens || 0) * pricing.cache_read_input_token_cost

  // 5. 计算缓存创建成本
  let ephemeral5mCost = 0
  let ephemeral1hCost = 0
  let cacheCreateCost = 0

  if (usage.cache_creation && typeof usage.cache_creation === 'object') {
    // 新格式: 区分 5 分钟和 1 小时缓存
    const ephemeral5mTokens = usage.cache_creation.ephemeral_5m_input_tokens || 0
    const ephemeral1hTokens = usage.cache_creation.ephemeral_1h_input_tokens || 0

    // 5 分钟缓存: 使用标准缓存创建价格
    ephemeral5mCost = ephemeral5mTokens * pricing.cache_creation_input_token_cost

    // 1 小时缓存: 使用硬编码价格
    const ephemeral1hPrice = this.getEphemeral1hPricing(modelName)
    ephemeral1hCost = ephemeral1hTokens * ephemeral1hPrice

    cacheCreateCost = ephemeral5mCost + ephemeral1hCost
  } else if (usage.cache_creation_input_tokens) {
    // 旧格式: 所有缓存创建按 5 分钟价格计算
    cacheCreateCost =
      (usage.cache_creation_input_tokens || 0) * pricing.cache_creation_input_token_cost
    ephemeral5mCost = cacheCreateCost
  }

  // 6. 计算总成本
  const totalCost = inputCost + outputCost + cacheReadCost + cacheCreateCost

  return {
    inputCost,
    outputCost,
    cacheCreateCost,
    cacheReadCost,
    ephemeral5mCost,
    ephemeral1hCost,
    totalCost,
    hasPricing: true,
    isLongContextRequest: useLongContextPricing
  }
}
```

#### 1 小时缓存价格 (硬编码)

```javascript
// ephemeral_1h 缓存价格 (美元/token)
this.ephemeral1hPricing = {
  // Opus 系列: $30/MTok
  'claude-opus-4-20250514': 0.00003,
  'claude-opus-4-1-20250805': 0.00003,

  // Sonnet 系列: $6/MTok
  'claude-sonnet-4-20250514': 0.000006,
  'claude-3-5-sonnet-20241022': 0.000006,

  // Haiku 系列: $1.6/MTok
  'claude-3-5-haiku-20241022': 0.0000016,
  'claude-3-haiku-20240307': 0.0000016
}

getEphemeral1hPricing(modelName) {
  // 直接匹配
  if (this.ephemeral1hPricing[modelName]) {
    return this.ephemeral1hPricing[modelName]
  }

  // 模糊匹配
  const modelLower = modelName.toLowerCase()
  if (modelLower.includes('opus')) return 0.00003
  if (modelLower.includes('sonnet')) return 0.000006
  if (modelLower.includes('haiku')) return 0.0000016

  return 0
}
```

#### 1M 上下文模型价格

```javascript
// 1M 上下文模型特殊价格
this.longContextPricing = {
  'claude-sonnet-4-20250514[1m]': {
    input: 0.000006,   // $6/MTok
    output: 0.0000225  // $22.50/MTok
  }
}
```

### 4. Usage 统计和更新

#### 速率限制计数器更新

```javascript
// 文件: src/utils/rateLimitHelper.js
async function updateRateLimitCounters(rateLimitInfo, usageSummary, model) {
  const client = redis.getClient()

  // 1. 计算总 tokens
  const totalTokens =
    (usageSummary.inputTokens || 0) +
    (usageSummary.outputTokens || 0) +
    (usageSummary.cacheCreateTokens || 0) +
    (usageSummary.cacheReadTokens || 0)

  // 2. 更新 token 计数
  if (totalTokens > 0 && rateLimitInfo.tokenCountKey) {
    await client.incrby(rateLimitInfo.tokenCountKey, Math.round(totalTokens))
  }

  // 3. 计算成本
  const usagePayload = {
    input_tokens: usageSummary.inputTokens,
    output_tokens: usageSummary.outputTokens,
    cache_creation_input_tokens: usageSummary.cacheCreateTokens,
    cache_read_input_tokens: usageSummary.cacheReadTokens
  }

  let totalCost = 0

  try {
    const costInfo = pricingService.calculateCost(usagePayload, model)
    totalCost = costInfo.totalCost || 0
  } catch (error) {
    // 使用备用计算器
    const fallback = CostCalculator.calculateCost(usagePayload, model)
    totalCost = fallback.costs?.total || 0
  }

  // 4. 更新成本计数
  if (totalCost > 0 && rateLimitInfo.costCountKey) {
    await client.incrbyfloat(rateLimitInfo.costCountKey, totalCost)
  }

  return { totalTokens, totalCost }
}
```

#### Redis 使用统计结构

```javascript
// Token 计数器
// key: rate_limit:token:{keyId}:{window}
// value: number

// 成本计数器
// key: rate_limit:cost:{keyId}:{window}
// value: float

// 使用记录
// key: api_key_usage:{keyId}
{
  totalTokens: 123456,
  totalCost: 0.123456,
  requestCount: 100,
  lastUsedAt: 1234567890,
  // 按日期和模型统计
  daily: {
    "2025-01-15": {
      "claude-sonnet-4": {
        inputTokens: 10000,
        outputTokens: 5000,
        cacheCreateTokens: 2000,
        cacheReadTokens: 500,
        cost: 0.045,
        requestCount: 10
      }
    }
  }
}

// 账户使用统计
// key: account_usage:{accountId}:{date}
{
  totalInputTokens: 50000,
  totalOutputTokens: 25000,
  totalCacheCreateTokens: 10000,
  totalCacheReadTokens: 2500,
  totalCost: 0.225,
  requestCount: 50,
  // 按模型分组
  models: {
    "claude-sonnet-4": { ... },
    "claude-opus-4": { ... }
  }
}
```

### 5. 成本计算示例

#### 示例 1: 标准请求

```javascript
// 请求参数
const usage = {
  input_tokens: 1000,
  output_tokens: 500,
  cache_creation_input_tokens: 0,
  cache_read_input_tokens: 0
}
const model = "claude-sonnet-4-20250514"

// 定价
const pricing = {
  input_cost_per_token: 0.000003,   // $3/MTok
  output_cost_per_token: 0.000015   // $15/MTok
}

// 计算
const inputCost = 1000 * 0.000003 = 0.003
const outputCost = 500 * 0.000015 = 0.0075
const totalCost = 0.003 + 0.0075 = 0.0105 美元
```

#### 示例 2: 带缓存的请求

```javascript
// 请求参数
const usage = {
  input_tokens: 1000,
  output_tokens: 500,
  cache_creation: {
    ephemeral_5m_input_tokens: 2000,
    ephemeral_1h_input_tokens: 3000
  },
  cache_read_input_tokens: 500
}
const model = "claude-sonnet-4-20250514"

// 定价
const pricing = {
  input_cost_per_token: 0.000003,
  output_cost_per_token: 0.000015,
  cache_creation_input_token_cost: 0.00000375,  // $3.75/MTok
  cache_read_input_token_cost: 0.0000003       // $0.3/MTok
}
const ephemeral1hPrice = 0.000006  // $6/MTok

// 计算
const inputCost = 1000 * 0.000003 = 0.003
const outputCost = 500 * 0.000015 = 0.0075
const ephemeral5mCost = 2000 * 0.00000375 = 0.0075
const ephemeral1hCost = 3000 * 0.000006 = 0.018
const cacheReadCost = 500 * 0.0000003 = 0.00015

const totalCost = 0.003 + 0.0075 + 0.0075 + 0.018 + 0.00015 = 0.03615 美元
```

#### 示例 3: 1M 上下文模型

```javascript
// 请求参数
const usage = {
  input_tokens: 250000,  // 超过 200k
  output_tokens: 5000,
  cache_creation_input_tokens: 0,
  cache_read_input_tokens: 0
}
const model = "claude-sonnet-4-20250514[1m]"

// 定价 (1M 上下文)
const longContextPricing = {
  input: 0.000006,   // $6/MTok
  output: 0.0000225  // $22.50/MTok
}

// 计算
const inputCost = 250000 * 0.000006 = 1.5
const outputCost = 5000 * 0.0000225 = 0.1125
const totalCost = 1.5 + 0.1125 = 1.6125 美元
```

---

## Python 复刻开发建议

### 1. 技术栈选型

#### 推荐框架和库

```python
# Web 框架
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
import uvicorn

# HTTP 客户端
import httpx  # 异步 HTTP 客户端,支持 HTTP/2
import aiohttp  # 备选方案

# Redis 客户端
import redis.asyncio as redis
from redis.asyncio import Redis

# 代理支持
from httpx_socks import AsyncProxyTransport  # SOCKS5
# httpx 原生支持 HTTP/HTTPS 代理

# 加密
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend
import hashlib
import secrets

# 日志
import logging
from logging.handlers import RotatingFileHandler

# 配置管理
from pydantic import BaseSettings
import yaml

# 异步任务
import asyncio
from apscheduler.schedulers.asyncio import AsyncIOScheduler
```

### 2. 项目结构建议

```
claude-relay-py/
├── app/
│   ├── __init__.py
│   ├── main.py                    # FastAPI 应用入口
│   ├── config.py                  # 配置管理
│   ├── models/                    # 数据模型
│   │   ├── __init__.py
│   │   ├── api_key.py
│   │   ├── account.py
│   │   └── usage.py
│   ├── services/                  # 业务逻辑
│   │   ├── __init__.py
│   │   ├── auth.py               # 认证服务
│   │   ├── scheduler.py          # 账户调度
│   │   ├── relay.py              # 代理转发
│   │   ├── pricing.py            # 定价服务
│   │   └── account_manager.py    # 账户管理
│   ├── utils/                     # 工具函数
│   │   ├── __init__.py
│   │   ├── crypto.py             # 加密工具
│   │   ├── proxy.py              # 代理工具
│   │   ├── redis_client.py       # Redis 客户端
│   │   └── logger.py             # 日志工具
│   └── routes/                    # 路由
│       ├── __init__.py
│       ├── api.py                # Claude API 路由
│       └── admin.py              # 管理接口
├── config/
│   ├── config.yaml               # 配置文件
│   └── model_pricing.json        # 模型定价
├── tests/                         # 测试
├── requirements.txt
└── README.md
```

### 3. 核心代码实现示例

#### 3.1 配置管理

```python
# app/config.py
from pydantic import BaseSettings
from typing import Optional
import yaml

class Settings(BaseSettings):
    # Redis
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_password: Optional[str] = None
    redis_db: int = 0

    # 安全
    encryption_key: str  # 32 字节 hex
    jwt_secret: str

    # Claude API
    claude_api_url: str = "https://api.claude.ai"
    claude_api_version: str = "2023-06-01"

    # 代理
    proxy_use_ipv4: bool = True

    # 请求超时
    request_timeout: int = 600  # 秒

    class Config:
        env_file = ".env"

settings = Settings()
```

#### 3.2 加密工具

```python
# app/utils/crypto.py
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend
import hashlib
import secrets
import json

class CryptoHelper:
    def __init__(self, encryption_key: str):
        """
        encryption_key: 32 字节的 hex 字符串
        """
        self.key = bytes.fromhex(encryption_key)

    def encrypt(self, data: dict) -> str:
        """AES-256-CBC 加密"""
        iv = secrets.token_bytes(16)
        cipher = Cipher(
            algorithms.AES(self.key),
            modes.CBC(iv),
            backend=default_backend()
        )
        encryptor = cipher.encryptor()

        # 序列化数据
        plaintext = json.dumps(data).encode('utf-8')

        # PKCS7 填充
        padding_length = 16 - (len(plaintext) % 16)
        plaintext += bytes([padding_length]) * padding_length

        # 加密
        ciphertext = encryptor.update(plaintext) + encryptor.finalize()

        # 返回 iv:ciphertext (hex)
        return iv.hex() + ':' + ciphertext.hex()

    def decrypt(self, encrypted_data: str) -> dict:
        """AES-256-CBC 解密"""
        iv_hex, ciphertext_hex = encrypted_data.split(':')
        iv = bytes.fromhex(iv_hex)
        ciphertext = bytes.fromhex(ciphertext_hex)

        cipher = Cipher(
            algorithms.AES(self.key),
            modes.CBC(iv),
            backend=default_backend()
        )
        decryptor = cipher.decryptor()

        # 解密
        plaintext = decryptor.update(ciphertext) + decryptor.finalize()

        # 去除 PKCS7 填充
        padding_length = plaintext[-1]
        plaintext = plaintext[:-padding_length]

        # 反序列化
        return json.loads(plaintext.decode('utf-8'))

    @staticmethod
    def hash_api_key(api_key: str, salt: str) -> str:
        """SHA-256 哈希"""
        return hashlib.sha256((api_key + salt).encode()).hexdigest()
```

#### 3.3 代理工具

```python
# app/utils/proxy.py
import httpx
from httpx_socks import AsyncProxyTransport
from typing import Optional

class ProxyHelper:
    @staticmethod
    def create_proxy_client(proxy_config: dict, timeout: int = 600) -> httpx.AsyncClient:
        """创建支持代理的 HTTP 客户端"""
        if not proxy_config or not proxy_config.get('enabled'):
            return httpx.AsyncClient(timeout=timeout)

        protocol = proxy_config['protocol']
        host = proxy_config['host']
        port = proxy_config['port']
        username = proxy_config.get('username')
        password = proxy_config.get('password')

        if protocol == 'socks5':
            # SOCKS5 代理
            proxy_url = f"socks5://{host}:{port}"
            if username and password:
                proxy_url = f"socks5://{username}:{password}@{host}:{port}"

            transport = AsyncProxyTransport.from_url(proxy_url)
            return httpx.AsyncClient(transport=transport, timeout=timeout)

        elif protocol in ['http', 'https']:
            # HTTP/HTTPS 代理
            proxy_url = f"{protocol}://{host}:{port}"
            if username and password:
                proxy_url = f"{protocol}://{username}:{password}@{host}:{port}"

            return httpx.AsyncClient(
                proxies={"https://": proxy_url, "http://": proxy_url},
                timeout=timeout
            )

        return httpx.AsyncClient(timeout=timeout)
```

#### 3.4 Redis 客户端

```python
# app/utils/redis_client.py
import redis.asyncio as redis
from typing import Optional, Any
import json

class RedisClient:
    def __init__(self, host: str, port: int, password: Optional[str] = None, db: int = 0):
        self.client = redis.Redis(
            host=host,
            port=port,
            password=password,
            db=db,
            decode_responses=True
        )

    async def get(self, key: str) -> Optional[dict]:
        """获取并反序列化 JSON"""
        data = await self.client.get(key)
        if data:
            return json.loads(data)
        return None

    async def set(self, key: str, value: dict, ex: Optional[int] = None):
        """序列化并存储 JSON"""
        await self.client.set(key, json.dumps(value), ex=ex)

    async def incr(self, key: str, amount: int = 1) -> int:
        """增加整数计数"""
        return await self.client.incrby(key, amount)

    async def incr_float(self, key: str, amount: float) -> float:
        """增加浮点数计数"""
        return await self.client.incrbyfloat(key, amount)

    async def hget(self, name: str, key: str) -> Optional[str]:
        """获取哈希字段"""
        return await self.client.hget(name, key)

    async def hset(self, name: str, key: str, value: str):
        """设置哈希字段"""
        await self.client.hset(name, key, value)
```

#### 3.5 定价服务

```python
# app/services/pricing.py
import json
import httpx
from pathlib import Path
from typing import Optional, Dict

class PricingService:
    def __init__(self):
        self.pricing_file = Path("config/model_pricing.json")
        self.pricing_data: Optional[Dict] = None

        # 1 小时缓存价格 (美元/token)
        self.ephemeral_1h_pricing = {
            # Opus: $30/MTok
            "claude-opus-4-20250514": 0.00003,
            # Sonnet: $6/MTok
            "claude-sonnet-4-20250514": 0.000006,
            # Haiku: $1.6/MTok
            "claude-3-5-haiku-20241022": 0.0000016,
        }

        # 1M 上下文价格
        self.long_context_pricing = {
            "claude-sonnet-4-20250514[1m]": {
                "input": 0.000006,
                "output": 0.0000225
            }
        }

    async def initialize(self):
        """加载定价数据"""
        if self.pricing_file.exists():
            with open(self.pricing_file, 'r') as f:
                self.pricing_data = json.load(f)
        else:
            # 下载远程定价数据
            await self.download_pricing()

    async def download_pricing(self):
        """从远程下载定价数据"""
        url = "https://example.com/model_pricing.json"
        async with httpx.AsyncClient() as client:
            response = await client.get(url)
            self.pricing_data = response.json()

            # 保存到本地
            with open(self.pricing_file, 'w') as f:
                json.dump(self.pricing_data, f, indent=2)

    def get_model_pricing(self, model_name: str) -> Optional[Dict]:
        """获取模型定价"""
        if not self.pricing_data:
            return None

        pricing = self.pricing_data.get(model_name)
        if pricing:
            return self._ensure_cache_pricing(pricing)
        return None

    def _ensure_cache_pricing(self, pricing: Dict) -> Dict:
        """确保缓存价格存在"""
        if 'cache_creation_input_token_cost' not in pricing:
            pricing['cache_creation_input_token_cost'] = \
                pricing['input_cost_per_token'] * 1.25

        if 'cache_read_input_token_cost' not in pricing:
            pricing['cache_read_input_token_cost'] = \
                pricing['input_cost_per_token'] * 0.1

        return pricing

    def get_ephemeral_1h_pricing(self, model_name: str) -> float:
        """获取 1 小时缓存价格"""
        if model_name in self.ephemeral_1h_pricing:
            return self.ephemeral_1h_pricing[model_name]

        # 模糊匹配
        model_lower = model_name.lower()
        if 'opus' in model_lower:
            return 0.00003
        elif 'sonnet' in model_lower:
            return 0.000006
        elif 'haiku' in model_lower:
            return 0.0000016

        return 0.0

    def calculate_cost(self, usage: Dict, model_name: str) -> Dict:
        """计算成本"""
        # 检查是否为 1M 上下文模型
        is_long_context = '[1m]' in model_name if model_name else False
        use_long_context_pricing = False

        if is_long_context:
            total_input = (
                usage.get('input_tokens', 0) +
                usage.get('cache_creation_input_tokens', 0) +
                usage.get('cache_read_input_tokens', 0)
            )
            if total_input > 200000:
                use_long_context_pricing = True

        # 获取定价
        pricing = self.get_model_pricing(model_name)

        if not pricing and not use_long_context_pricing:
            return {
                'input_cost': 0,
                'output_cost': 0,
                'cache_create_cost': 0,
                'cache_read_cost': 0,
                'total_cost': 0,
                'has_pricing': False
            }

        # 计算基础成本
        if use_long_context_pricing:
            long_prices = self.long_context_pricing.get(
                model_name,
                self.long_context_pricing.get(
                    list(self.long_context_pricing.keys())[0]
                )
            )
            input_cost = usage.get('input_tokens', 0) * long_prices['input']
            output_cost = usage.get('output_tokens', 0) * long_prices['output']
        else:
            input_cost = usage.get('input_tokens', 0) * pricing['input_cost_per_token']
            output_cost = usage.get('output_tokens', 0) * pricing['output_cost_per_token']

        # 缓存读取成本
        cache_read_cost = (
            usage.get('cache_read_input_tokens', 0) *
            pricing['cache_read_input_token_cost']
        )

        # 缓存创建成本
        ephemeral_5m_cost = 0
        ephemeral_1h_cost = 0

        cache_creation = usage.get('cache_creation')
        if isinstance(cache_creation, dict):
            # 新格式
            ephemeral_5m_tokens = cache_creation.get('ephemeral_5m_input_tokens', 0)
            ephemeral_1h_tokens = cache_creation.get('ephemeral_1h_input_tokens', 0)

            ephemeral_5m_cost = (
                ephemeral_5m_tokens *
                pricing['cache_creation_input_token_cost']
            )

            ephemeral_1h_price = self.get_ephemeral_1h_pricing(model_name)
            ephemeral_1h_cost = ephemeral_1h_tokens * ephemeral_1h_price
        else:
            # 旧格式
            cache_create_tokens = usage.get('cache_creation_input_tokens', 0)
            ephemeral_5m_cost = (
                cache_create_tokens *
                pricing['cache_creation_input_token_cost']
            )

        cache_create_cost = ephemeral_5m_cost + ephemeral_1h_cost

        # 总成本
        total_cost = input_cost + output_cost + cache_read_cost + cache_create_cost

        return {
            'input_cost': input_cost,
            'output_cost': output_cost,
            'cache_create_cost': cache_create_cost,
            'cache_read_cost': cache_read_cost,
            'ephemeral_5m_cost': ephemeral_5m_cost,
            'ephemeral_1h_cost': ephemeral_1h_cost,
            'total_cost': total_cost,
            'has_pricing': True,
            'is_long_context': use_long_context_pricing
        }
```

#### 3.6 Claude 代理服务

```python
# app/services/relay.py
import httpx
import json
from typing import Optional, Dict, AsyncIterator
from app.utils.proxy import ProxyHelper

class ClaudeRelayService:
    def __init__(self):
        self.api_url = "https://api.claude.ai"
        self.api_version = "2023-06-01"

    def _get_beta_header(self, model_id: Optional[str], client_beta: Optional[str]) -> str:
        """构建 anthropic-beta header"""
        OAUTH_BETA = "oauth-2025-04-20"
        CLAUDE_CODE_BETA = "claude-code-20250219"

        if client_beta:
            if OAUTH_BETA in client_beta:
                return client_beta

            parts = [p.strip() for p in client_beta.split(',')]

            if CLAUDE_CODE_BETA in parts:
                idx = parts.index(CLAUDE_CODE_BETA)
                parts.insert(idx + 1, OAUTH_BETA)
            else:
                parts.insert(0, OAUTH_BETA)

            return ','.join(parts)

        # 默认
        is_haiku = 'haiku' in (model_id or '').lower()
        if is_haiku:
            return "oauth-2025-04-20,interleaved-thinking-2025-05-14"

        return "claude-code-20250219,oauth-2025-04-20,interleaved-thinking-2025-05-14"

    async def relay_request(
        self,
        request_body: Dict,
        access_token: str,
        proxy_config: Optional[Dict] = None,
        client_headers: Optional[Dict] = None
    ) -> Dict:
        """非流式请求代理"""
        client = ProxyHelper.create_proxy_client(proxy_config)

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {access_token}",
            "anthropic-version": self.api_version,
            "anthropic-beta": self._get_beta_header(
                request_body.get('model'),
                client_headers.get('anthropic-beta') if client_headers else None
            ),
            "x-api-key": access_token
        }

        try:
            response = await client.post(
                f"{self.api_url}/api/v1/messages",
                json=request_body,
                headers=headers
            )

            return {
                "status_code": response.status_code,
                "headers": dict(response.headers),
                "body": response.json() if response.status_code == 200 else response.text
            }
        finally:
            await client.aclose()

    async def relay_stream_request(
        self,
        request_body: Dict,
        access_token: str,
        proxy_config: Optional[Dict] = None,
        client_headers: Optional[Dict] = None
    ) -> AsyncIterator[bytes]:
        """流式请求代理"""
        client = ProxyHelper.create_proxy_client(proxy_config)

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {access_token}",
            "anthropic-version": self.api_version,
            "anthropic-beta": self._get_beta_header(
                request_body.get('model'),
                client_headers.get('anthropic-beta') if client_headers else None
            ),
            "x-api-key": access_token
        }

        request_body['stream'] = True

        try:
            async with client.stream(
                "POST",
                f"{self.api_url}/api/v1/messages",
                json=request_body,
                headers=headers
            ) as response:
                # 收集 usage 数据
                usage_data = {}

                async for line in response.aiter_lines():
                    # 转发给客户端
                    yield (line + '\n').encode('utf-8')

                    # 解析 usage
                    if line.startswith('data:'):
                        json_str = line[5:].strip()
                        if json_str and json_str != '[DONE]':
                            try:
                                data = json.loads(json_str)

                                # message_start
                                if data.get('type') == 'message_start':
                                    msg_usage = data.get('message', {}).get('usage', {})
                                    usage_data['input_tokens'] = msg_usage.get('input_tokens', 0)
                                    usage_data['cache_creation_input_tokens'] = \
                                        msg_usage.get('cache_creation_input_tokens', 0)
                                    usage_data['cache_read_input_tokens'] = \
                                        msg_usage.get('cache_read_input_tokens', 0)
                                    usage_data['model'] = data.get('message', {}).get('model')

                                    # 详细缓存数据
                                    cache_creation = msg_usage.get('cache_creation')
                                    if isinstance(cache_creation, dict):
                                        usage_data['cache_creation'] = {
                                            'ephemeral_5m_input_tokens':
                                                cache_creation.get('ephemeral_5m_input_tokens', 0),
                                            'ephemeral_1h_input_tokens':
                                                cache_creation.get('ephemeral_1h_input_tokens', 0)
                                        }

                                # message_delta
                                elif data.get('type') == 'message_delta':
                                    usage = data.get('usage', {})
                                    if 'output_tokens' in usage:
                                        usage_data['output_tokens'] = usage['output_tokens']

                            except json.JSONDecodeError:
                                pass

                # 返回 usage 数据 (可以通过回调或其他方式处理)
                # 这里简化处理,实际应该通过回调函数处理
                if usage_data:
                    # await usage_callback(usage_data)
                    pass

        finally:
            await client.aclose()
```

#### 3.7 API 路由

```python
# app/routes/api.py
from fastapi import APIRouter, Request, HTTPException, Header
from fastapi.responses import StreamingResponse
from typing import Optional
from app.services.auth import AuthService
from app.services.scheduler import UnifiedClaudeScheduler
from app.services.relay import ClaudeRelayService
from app.services.pricing import PricingService

router = APIRouter()

auth_service = AuthService()
scheduler = UnifiedClaudeScheduler()
relay_service = ClaudeRelayService()
pricing_service = PricingService()

@router.post("/v1/messages")
async def claude_messages(
    request: Request,
    authorization: Optional[str] = Header(None)
):
    # 1. 验证 API Key
    if not authorization or not authorization.startswith('Bearer '):
        raise HTTPException(status_code=401, detail="Missing or invalid authorization")

    api_key = authorization[7:]  # 移除 "Bearer "
    api_key_data = await auth_service.authenticate_api_key(api_key)

    if not api_key_data:
        raise HTTPException(status_code=401, detail="Invalid API key")

    # 2. 解析请求体
    body = await request.json()

    # 3. 权限检查
    if api_key_data.get('permissions') not in ['all', 'claude']:
        raise HTTPException(status_code=403, detail="Permission denied")

    # 4. 选择账户
    session_hash = scheduler.generate_session_hash(body)
    account_selection = await scheduler.select_account_for_api_key(
        api_key_data,
        session_hash,
        body.get('model')
    )

    account_id = account_selection['account_id']
    account_type = account_selection['account_type']

    # 5. 获取访问 Token
    access_token = await auth_service.get_valid_access_token(account_id)

    # 6. 获取代理配置
    proxy_config = await scheduler.get_account_proxy_config(account_id)

    # 7. 判断是否流式
    is_stream = body.get('stream', False)

    if is_stream:
        # 流式响应
        async def stream_generator():
            async for chunk in relay_service.relay_stream_request(
                body,
                access_token,
                proxy_config,
                dict(request.headers)
            ):
                yield chunk

        return StreamingResponse(
            stream_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no"
            }
        )
    else:
        # 非流式响应
        response = await relay_service.relay_request(
            body,
            access_token,
            proxy_config,
            dict(request.headers)
        )

        if response['status_code'] == 200:
            # 提取 usage
            usage = response['body'].get('usage', {})

            # 计算成本
            cost_info = pricing_service.calculate_cost(usage, body.get('model'))

            # 更新统计
            await auth_service.update_usage_stats(
                api_key_data['id'],
                usage,
                cost_info,
                body.get('model')
            )

            return response['body']
        else:
            raise HTTPException(
                status_code=response['status_code'],
                detail=response['body']
            )
```

### 4. 关键差异和注意事项

#### 4.1 异步编程

Node.js 是单线程事件循环,JavaScript 原生支持 `async/await`。Python 需要显式使用 `asyncio` 和 `async/await`。

```python
# 所有 I/O 操作都应该是异步的
import asyncio

# 正确
async def fetch_data():
    async with httpx.AsyncClient() as client:
        response = await client.get(url)
        return response.json()

# 错误 (阻塞)
def fetch_data_blocking():
    response = requests.get(url)  # 同步调用,会阻塞事件循环
    return response.json()
```

#### 4.2 Redis 操作

```python
# Node.js (ioredis)
await redis.get(key)
await redis.set(key, value)
await redis.incrby(key, amount)

# Python (redis.asyncio)
await redis_client.get(key)
await redis_client.set(key, value)
await redis_client.incrby(key, amount)
```

#### 4.3 流式响应

```python
# FastAPI 流式响应
from fastapi.responses import StreamingResponse

async def stream_generator():
    async for chunk in some_async_iterator():
        yield chunk

return StreamingResponse(
    stream_generator(),
    media_type="text/event-stream"
)
```

#### 4.4 定时任务

```python
# Node.js
setInterval(() => {
  checkAndUpdate()
}, 24 * 60 * 60 * 1000)

# Python (APScheduler)
from apscheduler.schedulers.asyncio import AsyncIOScheduler

scheduler = AsyncIOScheduler()
scheduler.add_job(
    check_and_update,
    'interval',
    hours=24
)
scheduler.start()
```

### 5. 性能优化建议

#### 5.1 连接池

```python
# Redis 连接池
redis_pool = redis.ConnectionPool(
    host='localhost',
    port=6379,
    max_connections=50,
    decode_responses=True
)
redis_client = redis.Redis(connection_pool=redis_pool)

# HTTP 连接池 (httpx 自动管理)
async with httpx.AsyncClient(
    limits=httpx.Limits(max_keepalive_connections=20, max_connections=100)
) as client:
    ...
```

#### 5.2 缓存

```python
from functools import lru_cache
import asyncio

# 内存缓存 (装饰器)
@lru_cache(maxsize=1000)
def get_model_pricing(model_name: str):
    return pricing_data.get(model_name)

# 异步缓存 (需要第三方库或自实现)
from aiocache import cached

@cached(ttl=3600)  # 缓存 1 小时
async def get_account_info(account_id: str):
    return await redis_client.get(f"account:{account_id}")
```

#### 5.3 并发控制

```python
# 限制并发数
from asyncio import Semaphore

semaphore = Semaphore(10)  # 最多 10 个并发

async def process_with_limit():
    async with semaphore:
        await do_work()
```

### 6. 测试建议

```python
# tests/test_pricing.py
import pytest
from app.services.pricing import PricingService

@pytest.fixture
async def pricing_service():
    service = PricingService()
    await service.initialize()
    return service

@pytest.mark.asyncio
async def test_calculate_cost(pricing_service):
    usage = {
        'input_tokens': 1000,
        'output_tokens': 500,
        'cache_creation_input_tokens': 0,
        'cache_read_input_tokens': 0
    }
    model = "claude-sonnet-4-20250514"

    result = pricing_service.calculate_cost(usage, model)

    assert result['has_pricing'] == True
    assert result['total_cost'] > 0
    assert result['input_cost'] == 1000 * 0.000003
    assert result['output_cost'] == 500 * 0.000015

@pytest.mark.asyncio
async def test_calculate_cost_with_cache(pricing_service):
    usage = {
        'input_tokens': 1000,
        'output_tokens': 500,
        'cache_creation': {
            'ephemeral_5m_input_tokens': 2000,
            'ephemeral_1h_input_tokens': 3000
        },
        'cache_read_input_tokens': 500
    }
    model = "claude-sonnet-4-20250514"

    result = pricing_service.calculate_cost(usage, model)

    assert result['has_pricing'] == True
    assert result['ephemeral_5m_cost'] > 0
    assert result['ephemeral_1h_cost'] > 0
    assert result['cache_read_cost'] > 0
```

### 7. 部署建议

#### 7.1 使用 Uvicorn + Gunicorn

```bash
# 开发环境
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# 生产环境
gunicorn app.main:app \
  --workers 4 \
  --worker-class uvicorn.workers.UvicornWorker \
  --bind 0.0.0.0:8000 \
  --timeout 600 \
  --keep-alive 5
```

#### 7.2 Docker 部署

```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["gunicorn", "app.main:app", \
     "--workers", "4", \
     "--worker-class", "uvicorn.workers.UvicornWorker", \
     "--bind", "0.0.0.0:8000", \
     "--timeout", "600"]
```

---

## 总结

### 核心实现要点

1. **认证流程**: API Key SHA-256 哈希验证 + Redis 存储
2. **账户调度**: 多账户类型支持 + 会话粘性 + 负载均衡
3. **Token 管理**: OAuth 自动刷新 + AES-256 加密存储
4. **代理转发**: HTTPS 请求 + SOCKS5/HTTP 代理支持 + 流式响应
5. **Usage 捕获**: SSE 事件解析 (message_start + message_delta)
6. **成本计算**: 多层定价 (标准/缓存/1M上下文) + 详细缓存区分

### Python 复刻关键差异

| 方面 | Node.js | Python |
|-----|---------|--------|
| HTTP 客户端 | https 原生模块 | httpx (推荐) |
| Redis | ioredis | redis.asyncio |
| 异步模型 | 原生 async/await | asyncio + async/await |
| Web 框架 | Express.js | FastAPI |
| 代理 | socks-proxy-agent, https-proxy-agent | httpx-socks, httpx 原生 |
| 加密 | crypto 原生模块 | cryptography |
| 定时任务 | setInterval | APScheduler |

### 开发优先级建议

1. **阶段 1**: 核心功能
   - Redis 连接和数据模型
   - API Key 认证
   - 定价服务
   - 成本计算

2. **阶段 2**: 代理转发
   - Claude API 非流式请求
   - 账户管理和 Token 刷新
   - 代理支持

3. **阶段 3**: 高级功能
   - 流式响应和 Usage 捕获
   - 账户调度和会话粘性
   - 速率限制

4. **阶段 4**: 优化和扩展
   - 多账户类型支持
   - 缓存优化
   - 监控和日志

希望这份文档对您的 Python 复刻开发有所帮助!
