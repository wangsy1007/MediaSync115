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
      <img v-else class="feiniu-square-logo" :src="feiniuLogoUrl" alt="飞牛" referrerpolicy="no-referrer" />
    </span>
  </component>
</template>

<script setup>
import { computed } from 'vue'

const feiniuLogoUrl = 'https://www.fnnas.com/favicon.ico'

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

:global([data-theme='dark']) .library-badge__icon {
  background: rgba(10, 24, 50, 0.96);
  border-color: rgba(148, 194, 255, 0.38);
  box-shadow: 0 8px 16px rgba(2, 10, 24, 0.34);
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

.library-badge__icon.is-feiniu {
  padding: 0;
}

.library-badge__icon .feiniu-square-logo {
  width: 100%;
  height: 100%;
  border-radius: 50%;
  object-fit: cover;
  transform: scale(1.08);
}
</style>
