import type { ReactNode } from 'react'
import { createContext, useContext } from 'react'
import { useWallet } from '../hooks/useWallet'

const WalletContext = createContext<ReturnType<typeof useWallet> | null>(null)

interface WalletProviderProps {
  children: ReactNode
}

export const WalletProvider = ({ children }: WalletProviderProps) => {
  const walletState = useWallet()
  return <WalletContext.Provider value={walletState}>{children}</WalletContext.Provider>
}

export const useWalletContext = () => {
  const context = useContext(WalletContext)
  if (!context) {
    throw new Error('useWalletContext must be used within WalletProvider')
  }
  return context
}
