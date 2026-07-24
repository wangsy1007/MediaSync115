import { expect, test } from '@playwright/test'

async function waitForPageReady(page) {
  await page.waitForLoadState('domcontentloaded')
  await page.waitForLoadState('networkidle', { timeout: 20_000 }).catch(() => {})
}

test.describe('前端烟雾测试', () => {
  test('豆瓣探索首页可以渲染首屏榜单', async ({ page }) => {
    await page.goto('/explore/douban')
    await waitForPageReady(page)

    await expect(page.getByRole('heading', { name: '豆瓣榜单探索' })).toBeVisible()
    await expect(page.locator('.recommend-group').first()).toBeVisible()
    await expect(page.locator('.recommend-card').first()).toBeVisible()
  })

  test('更多榜单页面可以渲染卡片列表', async ({ page }) => {
    await page.goto('/explore/douban/section/movie_hot')
    await waitForPageReady(page)

    await expect(page.getByRole('button', { name: '返回探索' })).toBeVisible()
    await expect(page.locator('.movie-card').first()).toBeVisible()
    await expect(page.locator('.load-anchor')).toBeVisible()
  })

  test('豆瓣更多榜单进入详情时记录原栏目和影片', async ({ page }) => {
    await page.route('**/api/search/explore/section/movie_hot**', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          section: {
            key: 'movie_hot',
            title: '测试豆瓣热门电影',
            items: [{
              id: '1292052',
              douban_id: '1292052',
              media_type: 'movie',
              rank: 1,
              title: '肖申克的救赎',
              poster_url: null,
              rating: 9.7
            }],
            total: 1,
            start: 0,
            count: 1
          },
          emby_status_map: {},
          feiniu_status_map: {}
        })
      })
    })

    await page.goto('/explore/douban/section/movie_hot')
    const targetCard = page.locator('[data-item-key="douban:movie:1292052"]')
    await expect(targetCard).toBeVisible()
    await targetCard.click()
    await page.waitForURL(/\/douban\/movie\/1292052\?from=/)

    const returnContext = await page.evaluate(() => (
      JSON.parse(sessionStorage.getItem('mediasync115:detail-return') || 'null')
    ))
    expect(returnContext).toMatchObject({
      type: 'explore-section',
      source: 'douban',
      sectionKey: 'movie_hot',
      itemKey: 'douban:movie:1292052',
      itemIndex: 0
    })
  })

  test('更多榜单从详情返回后恢复已加载批次并定位原影片', async ({ page }) => {
    const requestedStarts = []
    await page.route('**/api/search/explore/meta**', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ tmdb_configured: true })
      })
    })
    await page.route('**/api/search/explore/section/movie_popular**', async (route) => {
      const url = new URL(route.request().url())
      const start = Number(url.searchParams.get('start') || 0)
      const limit = Number(url.searchParams.get('limit') || 30)
      requestedStarts.push(start)
      const items = Array.from({ length: limit }, (_, offset) => {
        const index = start + offset
        const tmdbId = index === 126 ? 272 : 100000 + index
        return {
          id: tmdbId,
          tmdb_id: tmdbId,
          media_type: 'movie',
          rank: index + 1,
          title: index === 126 ? '定位影片' : `测试影片 ${index + 1}`,
          poster_path: null,
          vote_average: 8
        }
      })
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          section: {
            key: 'movie_popular',
            title: '测试热门电影',
            items,
            total: 180,
            start,
            count: items.length
          },
          emby_status_map: {},
          feiniu_status_map: {}
        })
      })
    })
    await page.route('**/api/search/emby/status-map', (route) => (
      route.fulfill({ status: 200, contentType: 'application/json', body: '{"items":{}}' })
    ))
    await page.route('**/api/search/feiniu/status-map', (route) => (
      route.fulfill({ status: 200, contentType: 'application/json', body: '{"items":{}}' })
    ))
    await page.route('**/api/search/movie/272', (route) => (
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          id: 272,
          title: '定位影片',
          original_title: 'Target Movie',
          overview: '',
          poster: null,
          backdrop_path: null,
          vote: 8,
          release_date: '1994-01-01',
          genres: [],
          production_countries: [],
          runtime: 120
        })
      })
    ))

    await page.goto('/explore/tmdb/section/movie_popular')
    await waitForPageReady(page)

    const cards = page.locator('.movie-card')
    const scrollContainer = page.locator('.app-main')
    await expect.poll(async () => {
      await scrollContainer.evaluate((element) => {
        element.scrollTop = element.scrollHeight
      })
      return cards.count()
    }).toBeGreaterThanOrEqual(150)

    const targetKey = 'tmdb:movie:272'
    const targetCard = page.locator(`[data-item-key="${targetKey}"]`)
    await expect(targetCard).toBeVisible()
    await targetCard.click()
    await page.waitForURL(/\/movie\/272\?from=/)
    await expect(page.locator('.movie-detail-page h1.title')).toBeVisible()

    requestedStarts.length = 0
    await page.getByRole('button', { name: '返回' }).first().click()
    await page.waitForURL('/explore/tmdb/section/movie_popular')
    expect(requestedStarts).not.toContain(0)
    await expect(targetCard).toBeInViewport()

    await targetCard.click()
    await page.waitForURL(/\/movie\/272\?from=/)

    requestedStarts.length = 0
    await page.reload()
    await expect(page.locator('.movie-detail-page h1.title')).toBeVisible()
    await page.getByRole('button', { name: '返回' }).first().click()
    await page.waitForURL('/explore/tmdb/section/movie_popular')

    await expect.poll(() => cards.count()).toBeGreaterThanOrEqual(150)
    for (const start of [0, 30, 60, 90, 120]) {
      expect(requestedStarts).toContain(start)
    }
    await expect(targetCard).toBeInViewport()
    await expect.poll(async () => targetCard.evaluate((element) => {
      const container = element.closest('.app-main')
      if (!container) return false
      const cardRect = element.getBoundingClientRect()
      const containerRect = container.getBoundingClientRect()
      const cardCenter = cardRect.top + cardRect.height / 2
      const containerCenter = containerRect.top + containerRect.height / 2
      return Math.abs(cardCenter - containerCenter) < containerRect.height * 0.2
    })).toBe(true)
  })

  test('电影详情页可以打开并展示资源页签', async ({ page }) => {
    await page.goto('/movie/272')
    await waitForPageReady(page)

    await expect(page.locator('.movie-detail-page h1.title')).toBeVisible()
    await expect(page.getByRole('tab', { name: '115网盘' })).toBeVisible()
    await expect(page.getByRole('tab', { name: '磁力链接' })).toBeVisible()
    await expect(page.getByRole('tab', { name: 'ED2K' })).toBeVisible()
    await expect(page.getByRole('button', { name: /用 Nullbr 获取资源|刷新 Nullbr/ })).toBeVisible()

    await page.getByRole('tab', { name: 'HDHive' }).click()
    await expect(page.getByRole('button', { name: /用 HDHive 获取资源|刷新 HDHive/ })).toBeVisible()
  })

  test('剧集详情页可以打开并展示选集相关操作', async ({ page }) => {
    await page.goto('/tv/1399')
    await waitForPageReady(page)

    await expect(page.locator('.tv-detail-page h1.title')).toBeVisible()
    await expect(page.getByRole('tab', { name: '115网盘' })).toBeVisible()
    await expect(page.getByRole('button', { name: /用 Nullbr 获取资源|刷新 Nullbr/ })).toBeVisible()

    await page.getByRole('tab', { name: 'HDHive' }).click()
    await expect(page.getByRole('button', { name: /用 HDHive 获取资源|刷新 HDHive/ })).toBeVisible()
  })

  test('豆瓣详情页可以打开并展示匹配与资源网盘入口', async ({ page }) => {
    await page.goto('/douban/movie/1292052')
    await waitForPageReady(page)

    await expect(page.locator('.douban-detail-page h1.title')).toBeVisible()
    await expect(page.getByRole('button', { name: /匹配 TMDB|重新匹配 TMDB/ })).toBeVisible()
    await expect(page.getByRole('tab', { name: '115网盘' })).toBeVisible()
    await expect(page.getByRole('button', { name: /用 Nullbr 获取资源|刷新 Nullbr/ })).toBeVisible()

    await page.getByRole('tab', { name: 'HDHive' }).click()
    await expect(page.getByRole('button', { name: /用 HDHive 获取资源|刷新 HDHive/ })).toBeVisible()
  })
})
