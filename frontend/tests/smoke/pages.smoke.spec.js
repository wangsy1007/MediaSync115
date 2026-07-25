import { expect, test } from '@playwright/test'

async function waitForPageReady(page) {
  await page.waitForLoadState('domcontentloaded')
  await page.waitForLoadState('networkidle', { timeout: 20_000 }).catch(() => {})
}

async function assertNoPageError(page, action) {
  const jsErrors = []
  const onError = (err) => {
    jsErrors.push(String(err?.message || err))
  }
  page.on('pageerror', onError)
  try {
    await action()
  } finally {
    page.off('pageerror', onError)
  }
  expect(jsErrors, `页面出现未捕获 JS 错误: ${jsErrors.join(' | ')}`).toEqual([])
}

const managementPages = [
  { name: '订阅管理', path: '/subscriptions', heading: '我的订阅', root: '.subscriptions-page' },
  { name: '离线下载', path: '/downloads', heading: '离线下载', root: '.downloads-page' },
  { name: '归档刮削', path: '/archive', heading: '归档刮削', root: '.archive-page' },
  { name: 'STRM 设置', path: '/strm', heading: 'STRM 设置', root: '.strm-page' },
  { name: '系统设置', path: '/settings', heading: '系统设置', root: '.settings-page' },
  { name: '我的片单', path: '/watchlists', heading: '我的片单', root: '.watchlists-page' },
  { name: '演职员关注', path: '/person-follows', heading: '演职员关注', root: '.person-follows-page' },
  { name: '调度中心', path: '/scheduler', heading: '调度中心', root: '.scheduler-page' },
  { name: '工作流', path: '/workflow', heading: '工作流', root: '.workflow-page' },
  { name: '日志中心', path: '/logs', heading: '日志中心', root: '.logs-page' },
]

test.describe('管理页与探索入口烟雾测试', () => {
  for (const pageInfo of managementPages) {
    test(`${pageInfo.name}页面可以渲染`, async ({ page }) => {
      await assertNoPageError(page, async () => {
        await page.goto(pageInfo.path)
        await waitForPageReady(page)
        await expect(page.locator(pageInfo.root)).toBeVisible()
        await expect(page.getByRole('heading', { name: pageInfo.heading })).toBeVisible()
      })
    })
  }

  test('TMDB 探索首页可以渲染', async ({ page }) => {
    await assertNoPageError(page, async () => {
      await page.goto('/explore/tmdb')
      await waitForPageReady(page)
      await expect(page.getByRole('heading', { name: 'TMDB 榜单探索' })).toBeVisible()
    })
  })

  test('猫眼探索首页可以渲染', async ({ page }) => {
    await assertNoPageError(page, async () => {
      await page.goto('/explore/maoyan')
      await waitForPageReady(page)
      await expect(page.getByRole('heading', { name: '猫眼榜单探索' })).toBeVisible()
    })
  })
})
