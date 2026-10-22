<script setup>
import { computed } from 'vue'
import { renderMarkdown } from '../lib/markdown.js'

const props = defineProps({ content: { type: String, default: '' } })
const html = computed(() => renderMarkdown(props.content))
</script>

<template>
  <div class="markdown-message" v-html="html"></div>
</template>
