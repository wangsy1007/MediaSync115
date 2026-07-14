<template>
  <el-dialog
    v-model="state.visible"
    :title="dialogTitle"
    width="380px"
    align-center
    append-to-body
    :show-close="state.phase === 'result'"
    :close-on-click-modal="state.phase === 'result'"
    :close-on-press-escape="state.phase === 'result'"
    class="pan115-progress-dialog-wrap"
    @closed="handleClosed"
  >
    <div v-if="state.phase !== 'result'" class="pan115-progress-panel">
      <el-icon class="pan115-progress-panel__spinner is-loading" aria-hidden="true">
        <Loading />
      </el-icon>
      <p v-if="state.resourceLabel" class="pan115-progress-panel__resource">{{ state.resourceLabel }}</p>
      <p class="pan115-progress-panel__message">{{ state.message }}</p>
    </div>

    <div v-else class="pan115-progress-result" :class="`is-${state.status}`">
      <div class="pan115-progress-result__icon" aria-hidden="true">
        <el-icon v-if="state.status === 'success'"><CircleCheckFilled /></el-icon>
        <el-icon v-else-if="state.status === 'warning'"><WarningFilled /></el-icon>
        <el-icon v-else><CircleCloseFilled /></el-icon>
      </div>
      <p v-if="state.resourceLabel" class="pan115-progress-result__resource">{{ state.resourceLabel }}</p>
      <p class="pan115-progress-result__message">{{ state.message }}</p>
    </div>

    <template v-if="state.phase === 'result'" #footer>
      <el-button type="primary" @click="handleConfirm">知道了</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import {
  CircleCheckFilled,
  CircleCloseFilled,
  Loading,
  WarningFilled,
} from '@element-plus/icons-vue'
import { computed } from 'vue'

const props = defineProps({
  state: {
    type: Object,
    required: true,
  },
})

const emit = defineEmits(['close'])

const dialogTitle = computed(() => {
  if (props.state.phase === 'unlock') return 'HDHive 解锁中'
  if (props.state.phase === 'transfer') return '115 转存中'
  if (props.state.status === 'success') return 'HDHive 解锁并转存成功'
  if (props.state.status === 'warning') return '转存提示'
  return 'HDHive 解锁后转存失败'
})

const handleConfirm = () => {
  props.state.visible = false
}

const handleClosed = () => {
  if (props.state.phase === 'result') {
    emit('close')
  }
}
</script>

<style scoped lang="scss">
.pan115-progress-panel {
  text-align: center;
  padding: 8px 0 12px;

  &__spinner {
    font-size: 36px;
    color: var(--ms-accent-primary, #60a5fa);
    margin-bottom: 14px;
  }

  &__resource {
    margin: 0 0 8px;
    font-size: 15px;
    font-weight: 600;
    color: var(--ms-text-primary);
    word-break: break-word;
  }

  &__message {
    margin: 0;
    font-size: 14px;
    line-height: 1.6;
    color: var(--ms-text-secondary);
    word-break: break-word;
  }
}

.pan115-progress-result {
  text-align: center;
  padding: 4px 0 8px;

  &__icon {
    display: flex;
    justify-content: center;
    margin-bottom: 12px;
    font-size: 42px;
  }

  &.is-success .pan115-progress-result__icon {
    color: #4ade80;
  }

  &.is-warning .pan115-progress-result__icon {
    color: #fbbf24;
  }

  &.is-failed .pan115-progress-result__icon {
    color: #f87171;
  }

  &__resource {
    margin: 0 0 8px;
    font-size: 15px;
    font-weight: 600;
    color: var(--ms-text-primary);
    word-break: break-word;
  }

  &__message {
    margin: 0;
    font-size: 14px;
    line-height: 1.6;
    color: var(--ms-text-secondary);
    word-break: break-word;
  }
}
</style>

<style lang="scss">
.el-dialog.pan115-progress-dialog-wrap {
  width: min(92vw, 380px) !important;
  max-width: 92vw;
  margin: auto !important;

  .el-dialog__body {
    padding-top: 8px;
    padding-bottom: 4px;
  }
}
</style>
