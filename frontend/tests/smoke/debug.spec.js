import { expect, test } from '@playwright/test'

const pages = [
  { name: '豆瓣探索首页', path: '/explore/douban' },
  { name: '热门电影榜单', path: '/explore/douban/section/movie_hot' },
  { name: '热门剧集榜单', path: '/explore/douban/section/tv_hot' },
  { name: '电影详情页', path: '/movie/272' },
  { name: '剧集详情页', path: '/tv/1399' },
  { name: '豆瓣电影详情', path: '/douban/movie/1292052' },
  { name: '订阅管理页', path: '/subscriptions' },
  { name: '下载管理页', path: '/downloads' },
  { name: '操作日志页', path: '/logs' },
  { name: '设置页', path: '/settings' },
  { name: '定时任务页', path: '/scheduler' },
  { name: '工作流页', path: '/workflow' },
]

test.describe.configure({ mode: 'serial' })

const allResults = []

test.describe('前端自动化调试', () => {
  for (const pageInfo of pages) {
    test(`${pageInfo.name} [${pageInfo.path}]`, async ({ page }) => {
      const result = {
        name: pageInfo.name,
        path: pageInfo.path,
        consoleErrors: [],
        consoleWarnings: [],
        slowRequests: [],
        failedRequests: [],
        loadTime: 0,
        domReady: 0,
        networkIdle: 0,
        jsErrors: [],
      }

      page.on('console', (msg) => {
        const text = msg.text()
        const location = msg.location()
        const locStr = location ? `${location.url}:${location.lineNumber}:${location.columnNumber}` : ''

        if (msg.type() === 'error') {
          if (!text.includes('Download the React DevTools') && !text.includes('DevTools failed')) {
            result.consoleErrors.push({ text, location: locStr })
          }
        }
        if (msg.type() === 'warning') {
          result.consoleWarnings.push({ text, location: locStr })
        }
      })

      page.on('pageerror', (err) => {
        result.jsErrors.push(err.message)
      })

      page.on('requestfailed', (request) => {
        result.failedRequests.push({
          url: request.url(),
          method: request.method(),
          failure: request.failure()?.errorText || 'unknown',
        })
      })

      const requestStartTimes = new Map()

      page.on('request', (request) => {
        requestStartTimes.set(request.url(), Date.now())
      })

      page.on('requestfinished', (request) => {
        const startTime = requestStartTimes.get(request.url())
        if (startTime) {
          const duration = Date.now() - startTime
          if (duration > 3000) {
            const response = request.response()
            result.slowRequests.push({
              url: request.url(),
              method: request.method(),
              status: typeof response?.status === 'function' ? response.status() : (response?.status || 0),
              durationMs: duration,
            })
          }
        }
      })

      const startTime = Date.now()

      try {
        const response = await page.goto(pageInfo.path, { waitUntil: 'domcontentloaded', timeout: 30_000 })
        result.domReady = Date.now() - startTime

        if (!response || !response.ok()) {
          result.failedRequests.push({
            url: pageInfo.path,
            method: 'GET',
            failure: `HTTP ${response?.status() || 'no response'}`,
          })
        }

        await page.waitForLoadState('networkidle', { timeout: 25_000 }).catch(() => {})
        result.networkIdle = Date.now() - startTime
        result.loadTime = Date.now() - startTime
      } catch (err) {
        result.loadTime = Date.now() - startTime
        result.jsErrors.push(`Navigation failed: ${err.message}`)
      }

      allResults.push(result)

      console.log(`\n========== ${pageInfo.name} (${pageInfo.path}) ==========`)
      console.log(`  DOM Ready: ${result.domReady}ms | Network Idle: ${result.networkIdle}ms | Total: ${result.loadTime}ms`)

      if (result.consoleErrors.length > 0) {
        console.log(`  [ERRORS] ${result.consoleErrors.length} console errors:`)
        result.consoleErrors.forEach((e, i) => console.log(`    ${i + 1}. ${e.text}${e.location ? ` (${e.location})` : ''}`))
      }

      if (result.jsErrors.length > 0) {
        console.log(`  [JS ERRORS] ${result.jsErrors.length} JS errors:`)
        result.jsErrors.forEach((e, i) => console.log(`    ${i + 1}. ${e}`))
      }

      if (result.consoleWarnings.length > 0) {
        console.log(`  [WARNINGS] ${result.consoleWarnings.length} warnings:`)
        result.consoleWarnings.forEach((w, i) => console.log(`    ${i + 1}. ${w.text.substring(0, 200)}${w.location ? ` (${w.location})` : ''}`))
      }

      if (result.failedRequests.length > 0) {
        console.log(`  [FAILED REQUESTS] ${result.failedRequests.length}:`)
        result.failedRequests.forEach((r, i) => console.log(`    ${i + 1}. [${r.method}] ${r.url} - ${r.failure}`))
      }

      if (result.slowRequests.length > 0) {
        console.log(`  [SLOW REQUESTS >3s] ${result.slowRequests.length}:`)
        result.slowRequests.sort((a, b) => b.durationMs - a.durationMs).forEach((r, i) =>
          console.log(`    ${i + 1}. [${r.status}] ${r.durationMs}ms - ${r.url}`)
        )
      }

      if (result.consoleErrors.length === 0 && result.jsErrors.length === 0 &&
          result.failedRequests.length === 0 && result.slowRequests.length === 0) {
        console.log('  ✓ No issues found')
      }

      console.log('')
    })
  }

  test('汇总报告', async () => {
    console.log('\n\n╔══════════════════════════════════════════════════════════════╗')
    console.log('║                    调试汇总报告                            ║')
    console.log('╚══════════════════════════════════════════════════════════════╝\n')

    const totalPages = allResults.length
    const pagesWithErrors = allResults.filter(r => r.consoleErrors.length > 0 || r.jsErrors.length > 0)
    const pagesWithFailedReqs = allResults.filter(r => r.failedRequests.length > 0)
    const pagesWithSlowReqs = allResults.filter(r => r.slowRequests.length > 0)

    console.log(`总页面数: ${totalPages}`)
    console.log(`存在控制台错误的页面: ${pagesWithErrors.length}/${totalPages}`)
    console.log(`存在请求失败的页面: ${pagesWithFailedReqs.length}/${totalPages}`)
    console.log(`存在慢请求(>3s)的页面: ${pagesWithSlowReqs.length}/${totalPages}`)
    console.log('')

    console.log('--- 页面加载时间排行 (由慢到快) ---')
    const sorted = [...allResults].sort((a, b) => b.loadTime - a.loadTime)
    sorted.forEach((r, i) => {
      const flag = r.loadTime > 10000 ? ' ⚠' : r.loadTime > 5000 ? ' ●' : ''
      console.log(`  ${i + 1}. ${r.loadTime}ms${flag} - ${r.name}`)
    })
    console.log('')

    if (pagesWithErrors.length > 0) {
      console.log('--- 控制台错误汇总 ---')
      pagesWithErrors.forEach(r => {
        console.log(`  [${r.name}]`)
        r.consoleErrors.forEach(e => console.log(`    ERROR: ${e.text}`))
        r.jsErrors.forEach(e => console.log(`    JS ERROR: ${e}`))
      })
      console.log('')
    }

    if (pagesWithFailedReqs.length > 0) {
      console.log('--- 请求失败汇总 ---')
      pagesWithFailedReqs.forEach(r => {
        console.log(`  [${r.name}]`)
        r.failedRequests.forEach(req => console.log(`    [${req.method}] ${req.url} - ${req.failure}`))
      })
      console.log('')
    }

    if (pagesWithSlowReqs.length > 0) {
      console.log('--- 慢请求汇总 (>3s) ---')
      pagesWithSlowReqs.forEach(r => {
        console.log(`  [${r.name}]`)
        r.slowRequests.sort((a, b) => b.durationMs - a.durationMs).forEach(req =>
          console.log(`    ${req.durationMs}ms [${req.status}] ${req.url}`)
        )
      })
      console.log('')
    }

    const allWarnings = allResults.flatMap(r => r.consoleWarnings)
    if (allWarnings.length > 0) {
      console.log(`--- 所有警告 (${allWarnings.length} 条, 取前 20 条) ---`)
      allWarnings.slice(0, 20).forEach(w =>
        console.log(`    WARN: ${w.text.substring(0, 200)}${w.location ? ` (${w.location})` : ''}`)
      )
      if (allWarnings.length > 20) console.log(`    ... 还有 ${allWarnings.length - 20} 条警告`)
      console.log('')
    }

    console.log('--- 无问题的页面 ---')
    const cleanPages = allResults.filter(r =>
      r.consoleErrors.length === 0 && r.jsErrors.length === 0 &&
      r.failedRequests.length === 0 && r.slowRequests.length === 0
    )
    if (cleanPages.length === 0) {
      console.log('  (无)')
    } else {
      cleanPages.forEach(r => console.log(`  ✓ ${r.name} (${r.loadTime}ms)`))
    }
    console.log('')
  })
})
