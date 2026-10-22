import MarkdownIt from 'markdown-it'

// Model output is untrusted: escape raw HTML and retain markdown-it's URL validation.
const markdown = new MarkdownIt({ html: false, breaks: true, linkify: true })

markdown.renderer.rules.link_open = (tokens, index, options, env, renderer) => {
  tokens[index].attrSet('target', '_blank')
  tokens[index].attrSet('rel', 'noopener noreferrer')
  return renderer.renderToken(tokens, index, options)
}

// Do not load arbitrary remote images returned by the model.
markdown.renderer.rules.image = (tokens, index) => markdown.utils.escapeHtml(tokens[index].content)

markdown.renderer.rules.table_open = () =>
  '<div class="markdown-table" role="region" aria-label="回复表格，可横向滚动" tabindex="0"><table>\n'
markdown.renderer.rules.table_close = () => '</table></div>\n'

export function renderMarkdown(content) {
  return markdown.render(String(content ?? ''))
}
