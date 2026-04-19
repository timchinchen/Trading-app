import { create } from 'zustand'

interface AuthState {
  token: string | null
  mode: string | null
  setAuth: (token: string, mode: string) => void
  logout: () => void
}

export const useAuth = create<AuthState>((set) => ({
  token: localStorage.getItem('token'),
  mode: localStorage.getItem('mode'),
  setAuth: (token, mode) => {
    localStorage.setItem('token', token)
    localStorage.setItem('mode', mode)
    set({ token, mode })
  },
  logout: () => {
    localStorage.removeItem('token')
    localStorage.removeItem('mode')
    set({ token: null, mode: null })
  },
}))
