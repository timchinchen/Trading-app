import axios from 'axios'
import { useAuth } from '../store/auth'

export const api = axios.create({ baseURL: '/api' })

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
