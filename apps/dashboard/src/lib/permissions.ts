import { getToken, getRoleFromToken } from './api'

// Role hierarchy: superuser > owner > admin > engineer > analyst > viewer
const WRITE_ROLES   = new Set(['analyst', 'engineer', 'admin', 'owner', 'superuser'])
const APPROVE_ROLES = new Set(['engineer', 'admin', 'owner', 'superuser'])
const ADMIN_ROLES   = new Set(['admin', 'owner', 'superuser'])

export function usePermissions() {
  const role = getRoleFromToken(getToken())
  return {
    role,
    canWrite:   WRITE_ROLES.has(role),
    canApprove: APPROVE_ROLES.has(role),
    canAdmin:   ADMIN_ROLES.has(role),
  }
}
