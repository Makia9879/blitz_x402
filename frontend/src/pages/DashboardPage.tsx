import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useWalletContext } from '../context/WalletContext'
import { fetchBalance, type BalanceSummary } from '../services/api'

const PRETTY_STATUS: Record<string, string> = {
  idle: '待连接',
  connecting: '连接中',
  connected: '已连接',
  error: '异常',
}

const statusStyles: Record<string, string> = {
  idle: 'border-amber-400/40 bg-amber-400/10 text-amber-100',
  connecting: 'border-blue-400/40 bg-blue-400/10 text-blue-100',
  connected: 'border-emerald-400/50 bg-emerald-400/10 text-emerald-100',
  error: 'border-rose-400/50 bg-rose-500/10 text-rose-100',
}

const shortenAddress = (account?: string) => {
  if (!account) return '--'
  return `${account.slice(0, 6)}...${account.slice(-4)}`
}

const formatAmount = (value?: number, currency?: string) => {
  if (typeof value !== 'number') return '--'
  const formatted = value.toLocaleString('zh-CN', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })
  return `${formatted} ${currency ?? ''}`.trim()
}

// const formatDate = (iso?: string) => {
//   if (!iso) return '--'
//   const date = new Date(iso)
//   if (Number.isNaN(date.getTime())) return '--'
//   return date.toLocaleString('zh-CN', { hour12: false })
// }

const DashboardPage = () => {
  const { wallet, connect, refresh, isConnected, targetNetwork } = useWalletContext()
  const navigate = useNavigate()
  const [balance, setBalance] = useState<BalanceSummary>()
  const [loadingBalance, setLoadingBalance] = useState(true)
  const [balanceError, setBalanceError] = useState<string>()
  // const pollingRef = useRef<number | undefined>(undefined)
  const mountedRef = useRef(true)

  const loadBalance = useCallback(
    async (withLoader = false) => {
      console.log('withLoader---', withLoader)
      // if (withLoader) {
      //   setLoadingBalance(true)
      // }
      try {
        const data = await fetchBalance()
        if (!mountedRef.current) return
        setBalance(data)
        setBalanceError(undefined)
      } catch (error) {
        if (!mountedRef.current) return
        const message = error instanceof Error ? error.message : '余额获取失败'
        setBalanceError(message)
      } finally {
        if (withLoader && mountedRef.current) {
          setLoadingBalance(false)
        }
      }
    },
    [setBalance, setBalanceError, setLoadingBalance],
  )

  useEffect(() => {
    loadBalance(true)
    // pollingRef.current = window.setInterval(() => {
    //   loadBalance()
    // }, 20000)
    // return () => {
    //   mountedRef.current = false
    //   if (pollingRef.current) {
    //     clearInterval(pollingRef.current)
    //   }
    // }
  }, [loadBalance])

  const walletStatusStyle = useMemo(
    () => statusStyles[wallet.status] ?? statusStyles.idle,
    [wallet.status],
  )

  const monSymbol = targetNetwork.nativeCurrency.symbol

  return (
    <div className="space-y-8">
      <header>
        <p className="text-sm uppercase tracking-[0.35em] text-white/60">Payment Console</p>
        <h1 className="mt-3 text-3xl font-semibold text-white">Monad 测试网钱包 & 充值管理</h1>
        <p className="mt-2 max-w-2xl text-sm text-white/70">
          通过 MetaMask 连接 Monad 测试网钱包，查看 MON 余额与目标链 ID，同时实时掌握充值余额并可一键跳转充值。
        </p>
      </header>

      <section className="grid gap-6 md:grid-cols-2">
        <div className="rounded-2xl border border-white/10 bg-white/5 p-8 shadow-glow backdrop-blur">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div>
              <p className="text-sm uppercase tracking-[0.3em] text-white/50">模块一</p>
              <h2 className="mt-2 text-2xl font-semibold text-white">连接 Monad 测试网</h2>
            </div>
            <span className={`rounded-full border px-4 py-1 text-xs ${walletStatusStyle}`}>
              {PRETTY_STATUS[wallet.status]}
            </span>
          </div>
          <div className="mt-6 space-y-3 text-sm text-white/80">
            <div className="flex items-center justify-between">
              <span className="text-white/50">账户地址</span>
              <span className="font-mono text-base text-white">{shortenAddress(wallet.account)}</span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-white/50">链 ID</span>
              <span>{wallet.chainId ?? '--'}</span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-white/50">
                测试网余额 ({monSymbol})
              </span>
              <span>{wallet.nativeBalance ?? '--'}</span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-white/50">目标网络</span>
              <span>{wallet.networkName ?? targetNetwork.chainName}</span>
            </div>
          </div>
          {wallet.errorMessage ? (
            <p className="mt-4 text-sm text-rose-300">{wallet.errorMessage}</p>
          ) : (
            <p className="mt-4 text-xs text-white/50">
              连接后系统会自动请求切换至 Monad Testnet，并监听账户与链变化，可手动刷新链上余额。
            </p>
          )}
          <div className="mt-6 flex gap-3">
            <button
              type="button"
              onClick={isConnected ? refresh : connect}
              className="flex-1 rounded-xl border border-cyan-400/50 bg-cyan-400/20 px-4 py-3 text-sm font-semibold text-white transition hover:bg-cyan-400/30 disabled:opacity-50"
              disabled={wallet.status === 'connecting'}
            >
              {wallet.status === 'connecting'
                ? '连接中...'
                : isConnected
                  ? '刷新 Monad 余额'
                  : '连接 Monad 测试网'}
            </button>
          </div>
        </div>

        <div className="rounded-2xl border border-cyan-500/30 bg-gradient-to-br from-slate-900/70 to-cyan-900/20 p-8 shadow-lg shadow-cyan-500/10">
          <div className="flex items-start justify-between">
            <div>
              <p className="text-sm uppercase tracking-[0.3em] text-white/60">模块二</p>
              <h2 className="mt-2 text-2xl font-semibold text-white">充值余额总览</h2>
            </div>
          </div>
          <div className="mt-8">
            <p className="text-sm text-white/60">可用余额</p>
            <p className="mt-2 text-4xl font-semibold text-white">
              {loadingBalance ? '----' : formatAmount(balance?.balance, balance?.currency)}
            </p>
            {/* <div className="mt-6 grid gap-4 sm:grid-cols-2">
              <div className="rounded-xl border border-white/10 bg-white/5 p-4">
                <p className="text-xs uppercase tracking-widest text-white/50">待确认入账</p>
                <p className="mt-2 text-2xl font-semibold text-white">
                  {loadingBalance ? '--' : formatAmount(balance?.pendingAmount, balance?.currency)}
                </p>
              </div>
              <div className="rounded-xl border border-white/10 bg-white/5 p-4">
                <p className="text-xs uppercase tracking-widest text-white/50">最近同步</p>
                <p className="mt-2 text-lg text-white">
                  {loadingBalance ? '--' : formatDate(balance?.updatedAt)}
                </p>
              </div>
            </div> */}
            {/* {balanceError && <p className="mt-4 text-sm text-rose-300">{balanceError}</p>} */}
            <button
              type="button"
              onClick={() => navigate('/recharge')}
              className="mt-6 w-full rounded-xl bg-gradient-to-r from-cyan-400 via-blue-500 to-indigo-600 px-4 py-3 text-sm font-semibold text-white shadow-glow transition hover:opacity-90"
            >
              去充值
            </button>
          </div>
        </div>
      </section>
    </div>
  )
}

export default DashboardPage
