import { get, post } from '../lib/http'
import type { Role } from './permissions'

export interface User {
  id: number
  username: string
  display_name: string
  role: Role
  active: boolean
  locked: boolean
  locked_until: string
  created_at: string
  created_by: string
  last_login_at: string
  password_changed_at: string
}
export interface Me extends User {
  permissions: string[]
  case_ids: number[]
  session: { expires_at: string; created_at: string }
}
export interface LoginResult {
  token: string
  token_type: string
  expires_at: string
  idle_timeout_minutes: number
  user: User
}

export const authApi = {
  login: (username: string, password: string) => post<LoginResult>('/api/auth/login', { username, password }),
  logout: () => post<{ ok: boolean }>('/api/auth/logout'),
  me: () => get<Me>('/api/auth/me'),
  changePassword: (current_password: string, new_password: string) =>
    post<{ ok: boolean }>('/api/auth/password', { current_password, new_password }),
}
