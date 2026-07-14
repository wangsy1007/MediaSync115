<template>
  <el-dialog
    v-model="visible"
    title="HDHive 积分解锁"
    width="400px"
    align-center
    append-to-body
    :close-on-click-modal="false"
    class="hdhive-unlock-dialog-wrap"
    @closed="handleClosed"
  >
    <div class="hdhive-unlock-panel">
      <div class="hdhive-unlock-panel__head">
        <p class="hdhive-unlock-panel__name">{{ resourceName }}</p>
        <span class="hdhive-unlock-panel__badge">{{ points }} 积分</span>
      </div>

      <p v-if="subtitle" class="hdhive-unlock-panel__subtitle">{{ subtitle }}</p>

      <dl v-if="metaItems.length" class="hdhive-unlock-panel__meta">
        <template v-for="item in metaItems" :key="item.label">
          <dt>{{ item.label }}</dt>
          <dd>{{ item.value }}</dd>
        </template>
      </dl>

      <p class="hdhive-unlock-panel__main">
        确认花费 <strong>{{ points }}</strong> 积分解锁该资源的 115 分享链接？
      </p>
      <p v-if="hint" class="hdhive-unlock-panel__hint">{{ hint }}</p>
    </div>

    <template #footer>
      <el-button @click="handleCancel">取消</el-button>
      <el-button type="primary" @click="handleConfirm">确认解锁并继续</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'

const props = defineProps({
  row: {
    type: Object,
    required: true,
  },
  reason: {
    type: String,
    default: '',
  },
})

const emit = defineEmits(['confirm', 'cancel'])

const visible = ref(false)
const resolved = ref(false)

const points = computed(() => Number(props.row?.unlock_points || 0))

const resourceName = computed(() => (
  String(props.row?.resource_name || props.row?.title || '当前资源').trim() || '当前资源'
))

const subtitle = computed(() => {
  const title = String(props.row?.title || '').trim()
  const name = String(props.row?.resource_name || '').trim()
  if (!title || !name || title === name) return ''
  return title
})

const formatListValue = (value) => {
  if (Array.isArray(value)) {
    const items = value.map((item) => String(item || '').trim()).filter(Boolean)
    return items.join(' / ')
  }
  const text = String(value || '').trim()
  return text
}

const metaItems = computed(() => {
  const items = []
  const size = String(props.row?.size || '').trim()
  const resolution = formatListValue(props.row?.resolution)
  const quality = formatListValue(props.row?.quality)

  if (size) items.push({ label: '大小', value: size })
  if (resolution) items.push({ label: '分辨率', value: resolution })
  if (quality) items.push({ label: '画质', value: quality })
  return items
})

const hint = computed(() => {
  const lockMessage = String(props.row?.hdhive_lock_message || '').trim()
  const reason = String(props.reason || '').trim()
  return reason || lockMessage || '解锁成功后将自动继续转存。'
})

onMounted(() => {
  visible.value = true
})

const handleConfirm = () => {
  resolved.value = true
  visible.value = false
}

const handleCancel = () => {
  resolved.value = false
  visible.value = false
}

const handleClosed = () => {
  emit(resolved.value ? 'confirm' : 'cancel')
}
</script>

<style scoped lang="scss">
.hdhive-unlock-panel {
  text-align: left;
  line-height: 1.6;

  &__head {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 12px;
    margin-bottom: 8px;
  }

  &__name {
    flex: 1;
    margin: 0;
    font-size: 15px;
    font-weight: 600;
    color: var(--ms-text-primary);
    word-break: break-word;
  }

  &__badge {
    flex-shrink: 0;
    padding: 2px 10px;
    border-radius: 999px;
    font-size: 12px;
    font-weight: 600;
    line-height: 1.5;
    color: #fcd34d;
    background: rgba(245, 158, 11, 0.15);
    border: 1px solid rgba(245, 158, 11, 0.35);
  }

  &__subtitle {
    margin: 0 0 12px;
    font-size: 13px;
    color: var(--ms-text-muted);
    word-break: break-word;
  }

  &__meta {
    display: grid;
    grid-template-columns: 56px 1fr;
    gap: 6px 12px;
    margin: 0 0 14px;
    padding: 10px 12px;
    border-radius: var(--ms-radius-md, 8px);
    background: var(--ms-bg-hover, rgba(148, 163, 184, 0.08));
    border: 1px solid var(--ms-border-color);

    dt {
      margin: 0;
      font-size: 12px;
      color: var(--ms-text-muted);
    }

    dd {
      margin: 0;
      font-size: 13px;
      color: var(--ms-text-secondary);
      word-break: break-word;
    }
  }

  &__main {
    margin: 0 0 8px;
    font-size: 14px;
    color: var(--ms-text-secondary);

    strong {
      color: #fcd34d;
      font-weight: 700;
    }
  }

  &__hint {
    margin: 0;
    font-size: 13px;
    color: var(--ms-text-muted);
    word-break: break-word;
  }
}
</style>

<style lang="scss">
.el-dialog.hdhive-unlock-dialog-wrap {
  width: min(92vw, 400px) !important;
  max-width: 92vw;
  margin: auto !important;

  .el-dialog__body {
    padding-top: 8px;
    padding-bottom: 4px;
  }

  .el-dialog__footer {
    display: flex;
    justify-content: flex-end;
    gap: 8px;
  }
}
</style>
