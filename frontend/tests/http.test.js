import assert from 'node:assert/strict'
import test from 'node:test'
import { createApiClient } from '../src/lib/http.js'

test('JSON requests carry the session cookie policy and CSRF header', async () => {
  let request
  const api = createApiClient({
    fetchImpl: async (url, options) => {
      request = { url, ...options }
      return Response.json({ user: { id: 'u1' } })
    },
  })
  const result = await api('/auth/login', { method: 'POST', body: '{}' })
  assert.equal(result.user.id, 'u1')
  assert.equal(request.url, '/api/auth/login')
  assert.equal(request.credentials, 'same-origin')
  assert.equal(request.headers.get('X-CityMate-Request'), '1')
  assert.equal(request.headers.get('Content-Type'), 'application/json')
  assert.equal(request.headers.has('Authorization'), false)
})

test('uploads let the browser supply the multipart boundary', async () => {
  const form = new FormData()
  form.append('file', new Blob(['image']), 'image.png')
  const api = createApiClient({
    fetchImpl: async (_, options) => {
      assert.equal(options.body, form)
      assert.equal(options.headers.has('Content-Type'), false)
      assert.equal(options.headers.get('X-CityMate-Request'), '1')
      return Response.json({ url: '/uploads/image.jpg' })
    },
  })
  await api('/uploads', { method: 'POST', body: form })
})

test('an anonymous page reload stays quiet but protected requests require login', async () => {
  const events = []
  const api = createApiClient({
    fetchImpl: async () => Response.json({ detail: '请先登录' }, { status: 401 }),
    onUnauthorized: (event) => events.push(event),
  })
  assert.equal(await api('/me', {}, true), null)
  await assert.rejects(api('/orders'), /请先登录/)
  assert.deepEqual(events, [{ silent: true }, { silent: false }])
})

test('server and network failures are preserved, including non-JSON errors', async () => {
  const unavailable = createApiClient({
    fetchImpl: async () => new Response('upstream unavailable', { status: 503 }),
  })
  await assert.rejects(unavailable('/shops'), /503/)
  const offline = createApiClient({
    fetchImpl: async () => {
      throw new Error('Network unavailable')
    },
  })
  await assert.rejects(offline('/shops'), /Network unavailable/)
})
