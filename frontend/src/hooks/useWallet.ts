import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

type WalletStatus = 'idle' | 'connecting' | 'connected' | 'error'

export interface WalletSnapshot {
  status: WalletStatus
  account?: string
  chainId?: string
  networkName?: string
  nativeBalance?: string
  errorMessage?: string
}

interface ChainMetadata {
  chainId: string
  chainName: string
  nativeCurrency: {
    name: string
    symbol: string
    decimals: number
  }
  rpcUrls: string[]
  blockExplorerUrls: string[]
}

const env = import.meta.env as Record<string, string | undefined>
const DEFAULT_CHAIN_ID = '0x4EAF'

const normalizeChainId = (value?: string) => {
  if (!value) return DEFAULT_CHAIN_ID
  if (value.startsWith('0x')) {
    return value
  }
  const numeric = Number(value)
  if (Number.isNaN(numeric)) {
    return DEFAULT_CHAIN_ID
  }
  return `0x${numeric.toString(16)}`
}

const MONAD_TESTNET: ChainMetadata = {
  chainId: normalizeChainId(env.VITE_MONAD_CHAIN_ID),
  chainName: env.VITE_MONAD_CHAIN_NAME ?? 'Monad Testnet',
  nativeCurrency: {
    name: env.VITE_MONAD_CURRENCY_NAME ?? 'Monad',
    symbol: env.VITE_MONAD_CURRENCY_SYMBOL ?? 'MON',
    decimals: 18,
  },
  rpcUrls: [env.VITE_MONAD_RPC_URL ?? 'https://testnet-rpc.monad.xyz'],
  blockExplorerUrls: [env.VITE_MONAD_EXPLORER_URL ?? 'https://testnet.monadscan.io'],
}

const formatBalance = (raw: string) => {
  try {
    const wei = BigInt(raw)
    const ether = Number(wei) / 1e18
    return ether.toFixed(4)
  } catch {
    return '0.0000'
  }
}

export const useWallet = () => {
  const [wallet, setWallet] = useState<WalletSnapshot>({ status: 'idle' })
  const currentAccount = useRef<string | undefined>(undefined)

  const ensureMonadChain = useCallback(async () => {
    if (!window.ethereum) {
      throw new Error('未检测到 MetaMask')
    }
    try {
      await window.ethereum.request({
        method: 'wallet_switchEthereumChain',
        params: [{ chainId: MONAD_TESTNET.chainId }],
      })
    } catch (error) {
      const errorWithCode = error as { code?: number }
      if (errorWithCode?.code === 4902) {
        await window.ethereum.request({
          method: 'wallet_addEthereumChain',
          params: [MONAD_TESTNET],
        })
        return
      }
      throw error
    }
  }, [])

  const hydrateAccount = useCallback(async (account: string) => {
    if (!window.ethereum) {
      throw new Error('未检测到 MetaMask')
    }
    await ensureMonadChain()
    currentAccount.current = account
    const balanceHex = (await window.ethereum.request({
      method: 'eth_getBalance',
      params: [account, 'latest'],
    })) as string

    setWallet({
      status: 'connected',
      account,
      chainId: MONAD_TESTNET.chainId,
      networkName: MONAD_TESTNET.chainName,
      nativeBalance: formatBalance(balanceHex),
    })
  }, [ensureMonadChain])

  const connect = useCallback(async () => {
    if (!window.ethereum) {
      setWallet({ status: 'error', errorMessage: '请先安装 MetaMask 扩展' })
      return
    }
    try {
      setWallet((prev) => ({ ...prev, status: 'connecting', errorMessage: undefined }))
      const accounts = (await window.ethereum.request({
        method: 'eth_requestAccounts',
      })) as string[]

      if (!accounts.length) {
        throw new Error('未找到可用账号')
      }
      console.log('connect---', accounts[0])
      await hydrateAccount(accounts[0])
    } catch (error) {
      const errorWithCode = error as { code?: number }
      if (errorWithCode?.code === 4001) {
        setWallet({ status: 'idle', errorMessage: '已取消连接请求' })
        return
      }
      const message = error instanceof Error ? error.message : '连接失败，请稍后重试'
      setWallet({ status: 'error', errorMessage: message })
    }
  }, [hydrateAccount])

  const refresh = useCallback(async () => {
    if (!currentAccount.current || !window.ethereum) {
      return
    }
    try {
      await hydrateAccount(currentAccount.current)
    } catch (error) {
      const message = error instanceof Error ? error.message : '刷新失败'
      setWallet((prev) => ({ ...prev, errorMessage: message }))
    }
  }, [hydrateAccount])

  useEffect(() => {
    const provider = window.ethereum
    if (!provider) return

    const handleAccountsChanged = (accounts: unknown) => {
      const list = Array.isArray(accounts) ? (accounts as string[]) : []
      if (!list.length) {
        currentAccount.current = undefined
        setWallet({ status: 'idle' })
        return
      }
      hydrateAccount(list[0]).catch((error: unknown) => {
        const message = error instanceof Error ? error.message : '账户变更失败'
        setWallet({ status: 'error', errorMessage: message })
      })
    }

    const handleChainChanged = () => {
      if (!currentAccount.current) return
      hydrateAccount(currentAccount.current).catch(
        (error: unknown) => {
          const message = error instanceof Error ? error.message : '链切换失败'
          setWallet({ status: 'error', errorMessage: message })
        },
      )
    }

    provider.on?.('accountsChanged', handleAccountsChanged)
    provider.on?.('chainChanged', handleChainChanged)

    return () => {
      provider.removeListener?.('accountsChanged', handleAccountsChanged)
      provider.removeListener?.('chainChanged', handleChainChanged)
    }
  }, [hydrateAccount])

  const isConnected = useMemo(() => wallet.status === 'connected', [wallet.status])
  console.log('useWallet---', wallet)
  return { wallet, connect, refresh, isConnected, targetNetwork: MONAD_TESTNET }
}
