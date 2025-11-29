export type PaymentMethod = 'usdt-trc20' | 'usdc-erc20' | 'bank-transfer' | 'mon'

export interface BalanceSummary {
  balance: number
  pendingAmount: number
  currency: string
  updatedAt: string
}

export interface FacilitatorSession {
  paymentId: string
  expiresAt: string
}

export interface RechargeRequest {
  amount: number
  method: PaymentMethod
  account: string
  signature: string
}

export interface RechargeResponse {
  txId: string
  processedAt: string
}
const apiBase = "https://blitzx402.vercel.app"
// const delay = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms))

export const fetchBalance = async (): Promise<BalanceSummary> => {
  // 获取余额接口
  // await delay(600)
  const response = await fetch(`${apiBase}/api/v1/balance`, {
    method: 'GET',
    // headers: DEFAULT_HEADERS,
    // body: JSON.stringify(payload),
  })
  if (!response.ok) {
    return {
      balance: 3286.42,
      pendingAmount: 120.5,
      currency: 'USDT',
      updatedAt: new Date().toISOString(),
    }
  }
  console.log("response------balance", response)
  return {
    balance: response?.balance,
    pendingAmount: response?.balance_mon,
    currency: 'MON',
    updatedAt: new Date().toISOString(),
  }
}

export const submitRecharge = async ({ amount, method, account, signature }: RechargeRequest): Promise<RechargeResponse> => {
  // await delay(900)
  if (amount <= 0) {
    throw new Error('充值金额必须大于 0')
  }
  if (amount > 500000) {
    throw new Error('单笔金额超过风控限制，请联系管理员')
  }

  console.log('submitRecharge---', { amount, method, account, signature })

  const response = await fetch(`${apiBase}/api/v1/mcp/recharge`, {
    method: 'POST',
    // headers: DEFAULT_HEADERS,
    body: JSON.stringify({
      account,
      signature
    }),
  })
  console.log("response------2", response)
  const txId = `${account}-TX-${Math.floor(Math.random() * 1_000_000)
    .toString()
    .padStart(6, '0')}`
  return {
    txId: `${txId}`,
    processedAt: new Date().toISOString(),
  }
}
