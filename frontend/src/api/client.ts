import axios from 'axios'
import { useAuth } from '../store/auth'

// In dev (and single-origin prod), Vite/Nginx proxy /api -> backend.
// In split-container prod, set VITE_API_URL=http://host:8000 at build time.
const baseURL = (import.meta as any).env?.VITE_API_URL || '/api'

export const api = axios.create({ baseURL })

api.interceptors.request.use((cfg) => {
  const token = useAuth.getState().token
  if (token) cfg.headers.Authorization = `Bearer ${token}`
  return cfg
})

api.interceptors.response.use(
  (r) => r,
  (err) => {
    if (err?.response?.status === 401) {
      useAuth.getState().logout()
    }
    return Promise.reject(err)
  },
)
