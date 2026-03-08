import { getToken, getRoleFromToken } from './api'

// Role hierarchy: owner > admin > engineer > analyst > viewer
const WRITE_ROLES   = new Set(['analyst', 'engineer', 'admin', 'owner'])
const APPROVE_ROLES = new Set(['engineer', 'admin', 'owner'])
const ADMIN_ROLES   = new Set(['admin', 'owner'])

export function usePermissions() {
  const role = getRoleFromToken(getToken())
  return {
    role,
    canWrite:   WRITE_ROLES.has(role),
    canApprove: APPROVE_ROLES.has(role),
    canAdmin:   ADMIN_ROLES.has(role),
  }
}
