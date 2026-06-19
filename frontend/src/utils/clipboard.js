export const copyText = async (value) => {
  const text = String(value || '').trim()
  if (!text) {
    throw new Error('缺少可复制内容')
  }
  await navigator.clipboard.writeText(text)
}
