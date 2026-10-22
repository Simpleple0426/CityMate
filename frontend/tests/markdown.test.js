import assert from 'node:assert/strict'
import test from 'node:test'
import { renderMarkdown } from '../src/lib/markdown.js'

test('renders headings, emphasis, lists, tables and fenced code', () => {
  const html = renderMarkdown(
    '# 推荐\n\n**餐厅**\n\n- 第一家\n- 第二家\n\n| 店名 | 人均 |\n| --- | --- |\n| 小馆 | 98 |\n\n```js\nconst n = 1\n```',
  )
  for (const tag of ['<h1>', '<strong>', '<ul>', '<li>', '<table>', '<th>', '<td>', '<pre>']) {
    assert.ok(html.includes(tag), tag)
  }
  assert.match(html, /class="markdown-table"/)
})

test('escapes HTML and blocks executable links and remote images', () => {
  const html = renderMarkdown(
    '<script>alert(1)</script>\n\n<img src=x onerror=alert(1)>\n\n[x](javascript:alert(1))\n\n[x](data:text/html,hello)\n\n![photo](https://example.com/tracker.png)',
  )
  assert.doesNotMatch(html, /<script|<img|href="(?:javascript|data):/i)
  assert.match(html, /&lt;script&gt;/)
  assert.match(html, /photo/)
})

test('opens valid links safely and leaves fenced HTML as text', () => {
  const html = renderMarkdown('[官网](https://example.com)\n\n```html\n<script>x</script>\n```')
  assert.match(html, /href="https:\/\/example.com"/)
  assert.match(html, /target="_blank" rel="noopener noreferrer"/)
  assert.match(html, /&lt;script&gt;x&lt;\/script&gt;/)
  assert.equal(renderMarkdown(null), '')
})
