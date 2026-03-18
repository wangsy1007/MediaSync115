import { execFileSync } from 'node:child_process'
import { existsSync, mkdirSync, writeFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'

async function waitForHttpOk(url, timeoutMs) {
  const startedAt = Date.now()
  let lastError = ''

  while (Date.now() - startedAt < timeoutMs) {
    try {
      const response = await fetch(url, { redirect: 'follow' })
      if (response.ok) return
      lastError = `HTTP ${response.status}`
    } catch (error) {
      lastError = String(error?.message || error || 'unknown error')
    }
    await new Promise((resolve) => setTimeout(resolve, 1000))
  }

  throw new Error(`service check failed for ${url}: ${lastError}`)
}

function resolveAuthStorageStatePath() {
  return resolve(process.cwd(), 'test-results/.auth/smoke-user.json')
}

function buildSessionCookie(baseUrl) {
  const repoRoot = resolve(process.cwd(), '..')
  const backendRoot = resolve(repoRoot, 'backend')
  const script = [
    'import sys',
    "sys.path.insert(0, '.')",
    'from app.services.auth_service import SESSION_COOKIE_NAME, auth_service',
    'from app.services.runtime_settings_service import runtime_settings_service',
    'username = runtime_settings_service.get_auth_username()',
    "print(SESSION_COOKIE_NAME + '\\t' + auth_service.build_session_token(username))",
  ].join('; ')
  const localPython = resolve(backendRoot, '.venv-buildcheck/bin/python')
  const command = existsSync(localPython) ? localPython : 'docker'
  const args = existsSync(localPython)
    ? ['-c', script]
    : ['exec', 'mediasync115', 'python', '-c', script]
  const token = execFileSync(command, args, {
    cwd: existsSync(localPython) ? backendRoot : repoRoot,
    encoding: 'utf-8',
  })
    .trim()
    .split('\t')

  const [name, value] = token
  const url = new URL(baseUrl)
  return {
    name,
    value,
    domain: url.hostname,
    path: '/',
    httpOnly: true,
    secure: false,
    sameSite: 'Lax',
  }
}

export default async function globalSetup(config) {
  const frontendBaseUrl = config.metadata?.frontendBaseUrl || 'http://127.0.0.1:5173'
  const backendHealthUrl = config.metadata?.backendHealthUrl || 'http://127.0.0.1:8000/health'
  await waitForHttpOk(backendHealthUrl, 30_000)
  await waitForHttpOk(frontendBaseUrl, 30_000)

  const storageStatePath = resolveAuthStorageStatePath()
  const sessionCookie = buildSessionCookie(frontendBaseUrl)
  mkdirSync(dirname(storageStatePath), { recursive: true })
  writeFileSync(
    storageStatePath,
    JSON.stringify(
      {
        cookies: [sessionCookie],
        origins: [],
      },
      null,
      2,
    ),
    'utf-8',
  )
}
