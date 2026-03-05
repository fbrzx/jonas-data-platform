import { getToken, getRoleFromToken } from './api'

export function usePermissions() {
  const role = getRoleFromToken(getToken())
  return {
    role,
    canWrite: role === 'admin' || role === 'analyst',
    canAdmin: role === 'admin',
    canApprove: role === 'admin',
  }
}
