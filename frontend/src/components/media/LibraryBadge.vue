<template>
  <component :is="tag" v-if="sources.length" class="library-badge" :class="{ 'is-inline': inline, 'is-multi': sources.length > 1 }" :title="badgeTitle">
    <span v-for="source in sources" :key="source" class="library-badge__icon" :class="`is-${source}`">
      <svg v-if="source === 'emby'" viewBox="0 0 512 512" aria-hidden="true">
        <path
          d="m97.1 229.4 26.5 26.5L0 379.5l132.4 132.4 26.5-26.5L282.5 609l141.2-141.2-26.5-26.5L512 326.5 379.6 194.1l-26.5 26.5L229.5 97z"
          fill="#52b54b"
          transform="translate(0 -97)"
        />
        <path d="M196.8 351.2v-193L366 254.7 281.4 303z" fill="#fff" />
      </svg>
      <svg v-else viewBox="0 0 40 41" aria-hidden="true">
        <path
          d="M28.5789 15.7916C28.1602 19.4483 27.4081 23.2724 25.9674 26.6748C24.733 29.5902 21.799 24.513 21.6439 23.1623C21.6082 20.7152 29.2147 10.2244 28.5789 15.7916ZM14.0328 26.6748C12.5921 23.2724 11.8385 19.4483 11.4213 15.7916C10.7855 10.2244 18.3935 20.7152 18.3563 23.1623C18.2012 24.5115 15.2672 29.5902 14.0328 26.6748ZM20.0001 20.4408C13.7397 8.58523 6.45425 7.11511 10.1404 22.8165C11.9036 30.3299 15.2594 33.3942 20.0001 25.5257C24.7408 33.3942 28.0966 30.3299 29.8598 22.8181C33.546 7.11666 26.2605 8.58833 20.0001 20.4392V20.4408Z"
          fill="currentColor"
        />
      </svg>
    </span>
  </component>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  inEmby: {
    type: Boolean,
    default: false
  },
  inFeiniu: {
    type: Boolean,
    default: false
  },
  inline: {
    type: Boolean,
    default: false
  }
})

const sources = computed(() => {
  const list = []
  if (props.inEmby) list.push('emby')
  if (props.inFeiniu) list.push('feiniu')
  return list
})

const tag = computed(() => (props.inline ? 'span' : 'div'))

const badgeTitle = computed(() => {
  if (props.inEmby && props.inFeiniu) return '已入库：Emby、飞牛'
  if (props.inEmby) return '已入库：Emby'
  if (props.inFeiniu) return '已入库：飞牛'
  return '已入库'
})
</script>

<style scoped>
.library-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.library-badge.is-inline {
  gap: 7px;
}

.library-badge.is-multi {
  gap: 0;
}

.library-badge__icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.96);
  border: 1.5px solid rgba(255, 255, 255, 0.92);
  box-shadow: 0 6px 14px rgba(15, 23, 42, 0.18);
  overflow: hidden;
}

.library-badge.is-inline .library-badge__icon {
  width: 28px;
  height: 28px;
}

.library-badge.is-multi .library-badge__icon + .library-badge__icon {
  margin-left: -6px;
}

.library-badge__icon svg {
  width: 16px;
  height: 16px;
  display: block;
}

.library-badge.is-inline .library-badge__icon svg {
  width: 18px;
  height: 18px;
}

.library-badge__icon.is-emby {
  border-color: rgba(82, 181, 75, 0.96);
}

.library-badge__icon.is-emby svg {
  color: #52b54b;
}

.library-badge__icon.is-feiniu {
  border-color: rgba(59, 130, 246, 0.96);
}

.library-badge__icon.is-feiniu svg {
  color: #2f80ff;
}
</style>
