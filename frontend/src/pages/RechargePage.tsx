import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { submitRecharge, type PaymentMethod } from '../services/api'
import { useWalletContext } from '../context/WalletContext'


const PRESET_AMOUNTS = [100, 200, 500, 1000, 2000, 5000]

const PAYMENT_METHODS: { key: PaymentMethod; label: string; desc: string }[] = [
  { key: 'mon', label: 'MON', desc: 'MON · 手续费低' }
  // { key: 'usdc-erc20', label: 'USDC · ERC20', desc: '以太坊生态 · 高安全性' },
  // { key: 'bank-transfer', label: '银行转账', desc: '对公账户 · 适合大额' },
]

const RechargePage = () => {
  const [selectedAmount, setSelectedAmount] = useState<number | null>(PRESET_AMOUNTS[2])
  const [customAmount, setCustomAmount] = useState('')
  const [method, setMethod] = useState<PaymentMethod>('mon')
  const [submitting, setSubmitting] = useState(false)
  const [resultId, setResultId] = useState<string>()
  const [error, setError] = useState<string>()
  const navigate = useNavigate()
  const { wallet } = useWalletContext()
  console.log('wallet-----charge', wallet)
  const { account } = wallet

  const amount = useMemo(() => {
    if (selectedAmount) return selectedAmount
    const parsed = Number(customAmount)
    return Number.isFinite(parsed) ? parsed : 0
  }, [selectedAmount, customAmount])


  const handleSubmit = async () => {
    if (!amount || amount <= 0) {
      setError('请输入有效的充值金额')
      return
    }
    if (!account) {
      setError('请先连接 Monad 测试网钱包')
      return
    }
    const provider = window.ethereum
    if (!provider) {
      setError('请先安装 MetaMask 扩展')
      return
    }
    try {
      setSubmitting(true)
      setError(undefined)
      const signaturePayload = [
        'Authorize Recharge',
        `Account: ${account}`,
        `Amount: ${amount}`,
        `Method: ${method}`,
        `Timestamp: ${new Date().toISOString()}`,
      ].join('\n')
      const signature = (await provider.request({
        method: 'personal_sign',
        params: [signaturePayload, account],
      })) as string
      const result = await submitRecharge({ amount, account, method, signature })
      setResultId(result.txId)
    } catch (err) {
      const errorWithCode = err as { code?: number }
      if (errorWithCode?.code === 4001) {
        setError('已取消签名请求')
        return
      }
      const message = err instanceof Error ? err.message : '充值请求失败'
      setError(message)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="space-y-8">
      <header className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <p className="text-sm uppercase tracking-[0.35em] text-white/60">Recharge</p>
          <h1 className="mt-2 text-3xl font-semibold text-white">用户充值中心</h1>
          <p className="mt-2 text-sm text-white/70">
            选择充值金额与方式，确认后系统会发起到账请求并返回追踪编号。
          </p>
        </div>
        <button
          type="button"
          onClick={() => navigate('/')}
          className="rounded-full border border-white/20 px-4 py-2 text-sm text-white/80 transition hover:border-white/50"
        >
          返回总览
        </button>
      </header>

      <div className="grid gap-6 lg:grid-cols-[1.1fr_0.9fr]">
        <section className="rounded-2xl border border-white/10 bg-white/5 p-8 backdrop-blur">
          <h2 className="text-xl font-semibold text-white">选择充值金额</h2>
          <p className="mt-2 text-sm text-white/60">支持快捷档位或自定义金额，单位为 USD 计价的稳定币。</p>

          <div className="mt-6 grid grid-cols-2 gap-3 md:grid-cols-3">
            {PRESET_AMOUNTS.map((value) => {
              const active = selectedAmount === value
              return (
                <button
                  key={value}
                  type="button"
                  onClick={() => {
                    setSelectedAmount(value)
                    setCustomAmount('')
                    setResultId(undefined)
                    setError(undefined)
                  }}
                  className={`rounded-2xl border px-4 py-3 text-sm font-semibold transition ${
                    active
                      ? 'border-cyan-400/70 bg-cyan-400/15 text-white shadow-glow'
                      : 'border-white/10 text-white/70 hover:border-white/40 hover:bg-white/5'
                  }`}
                >
                  {value.toLocaleString('zh-CN')} USDT
                </button>
              )
            })}
          </div>

          <label className="mt-6 block text-sm text-white/70">
            自定义金额
            <input
              type="number"
              placeholder="输入其他金额"
              value={customAmount}
              onChange={(event) => {
                setSelectedAmount(null)
                setCustomAmount(event.target.value)
                setResultId(undefined)
                setError(undefined)
              }}
              className="mt-2 w-full rounded-xl border border-white/15 bg-black/20 px-4 py-3 text-base text-white focus:border-cyan-400/60 focus:outline-none"
            />
          </label>

          <h2 className="mt-8 text-xl font-semibold text-white">选择充值方式</h2>
          <div className="mt-4 grid gap-3 md:grid-cols-3">
            {PAYMENT_METHODS.map((item) => {
              const active = method === item.key
              return (
                <button
                  key={item.key}
                  type="button"
                  onClick={() => {
                    setMethod(item.key)
                    setResultId(undefined)
                    setError(undefined)
                  }}
                  className={`rounded-2xl border px-4 py-4 text-left transition ${
                    active
                      ? 'border-cyan-400/60 bg-gradient-to-br from-cyan-500/20 to-indigo-500/10 text-white'
                      : 'border-white/10 bg-white/5 text-white/70 hover:border-white/40'
                  }`}
                >
                  <p className="text-base font-semibold">{item.label}</p>
                  <p className="mt-2 text-xs text-white/60">{item.desc}</p>
                </button>
              )
            })}
          </div>

          {error && <p className="mt-4 text-sm text-rose-300">{error}</p>}
          {resultId && (
            <p className="mt-4 text-sm text-emerald-300">
              充值请求已提交，追踪编号：<span className="font-mono">{resultId}</span>
            </p>
          )}

          <button
            type="button"
            onClick={handleSubmit}
            disabled={submitting }
            className="mt-6 w-full rounded-2xl bg-gradient-to-r from-cyan-400 via-sky-500 to-indigo-600 px-6 py-3 text-sm font-semibold text-white shadow-glow transition hover:opacity-90 disabled:opacity-40"
          >
            {submitting ? '提交中...' : '发起充值请求'}
          </button>
        </section>

        <section className="rounded-2xl border border-white/10 bg-gradient-to-br from-slate-900/70 to-indigo-900/30 p-8">
          <h3 className="text-lg font-semibold text-white">充值信息摘要</h3>
          <div className="mt-6 space-y-4 text-sm text-white/70">
            <div className="flex items-center justify-between rounded-xl border border-white/10 bg-black/20 p-4">
              <div>
                <p className="text-xs uppercase tracking-widest text-white/50">预计到账金额</p>
                <p className="mt-2 text-3xl font-semibold text-white">{amount.toFixed(2)} USDT</p>
              </div>
              <span className="rounded-full border border-white/20 px-3 py-1 text-xs text-white/60">
                免手续费
              </span>
            </div>
            <div className="rounded-xl border border-white/10 bg-black/20 p-4">
              <p className="text-xs uppercase tracking-widest text-white/50">充值方式</p>
              <p className="mt-2 text-lg text-white">
                {PAYMENT_METHODS.find((i) => i.key === method)?.label ?? '--'}
              </p>
              <p className="mt-1 text-xs text-white/60">
                {PAYMENT_METHODS.find((i) => i.key === method)?.desc ?? ''}
              </p>
            </div>
            <div className="rounded-xl border border-white/10 bg-black/20 p-4">
              <p className="text-xs uppercase tracking-widest text-white/50">链路提示</p>
              <ul className="mt-3 space-y-2 text-xs leading-relaxed text-white/70">
                <li>• 链上方式平均 1-3 分钟到账。</li>
                <li>• 银行方式需上传转账回执，客服将人工审核。</li>
                <li>• 提交后可在总览页查看余额变动。</li>
              </ul>
            </div>
          </div>
        </section>
      </div>
    </div>
  )
}

export default RechargePage
