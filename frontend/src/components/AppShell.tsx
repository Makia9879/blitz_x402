import type { ReactNode } from 'react'
import { NavLink } from 'react-router-dom'

const navLinks = [
  { label: '资产概览', path: '/' },
  { label: '充值中心', path: '/recharge' },
]

interface AppShellProps {
  children: ReactNode
}

const AppShell = ({ children }: AppShellProps) => {
  return (
    <div className="relative min-h-screen overflow-hidden bg-[#030712] text-slate-100">
      <div className="pointer-events-none absolute inset-0 opacity-70">
        <div className="absolute inset-y-0 left-1/4 w-64 bg-cyan-500/20 blur-[180px]" />
        <div className="absolute inset-y-0 right-0 w-72 bg-indigo-500/20 blur-[220px]" />
        <div className="absolute inset-x-0 top-0 h-24 bg-gradient-to-b from-white/5 to-transparent" />
      </div>
      <div className="relative z-10 flex min-h-screen flex-col">
        <header className="border-b border-white/5 bg-white/5/50 backdrop-blur">
          <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-4 px-6 py-4">
            <div>
              <p className="text-sm uppercase tracking-[0.3em] text-white/60">User Payment</p>
              <p className="text-xl font-semibold text-cyan-300">NovaPay Platform</p>
            </div>
            <nav className="flex flex-wrap gap-2 text-sm font-medium">
              {navLinks.map((item) => (
                <NavLink
                  key={item.path}
                  to={item.path}
                  className={({ isActive }) =>
                    [
                      'rounded-full border px-4 py-2 transition-colors',
                      isActive
                        ? 'border-cyan-400/60 bg-cyan-400/10 text-white'
                        : 'border-white/10 text-white/70 hover:border-cyan-400/40 hover:text-white',
                    ].join(' ')
                  }
                >
                  {item.label}
                </NavLink>
              ))}
            </nav>
          </div>
        </header>
        <main className="mx-auto w-full max-w-6xl flex-1 px-6 py-10">{children}</main>
        <footer className="border-t border-white/5 bg-white/5/30 py-4 text-center text-xs text-white/60">
          支持 MetaMask & 链上实时记账 · 构建下一代 Web3 支付体验
        </footer>
      </div>
    </div>
  )
}

export default AppShell
