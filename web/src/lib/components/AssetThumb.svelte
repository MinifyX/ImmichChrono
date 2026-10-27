<script lang="ts">
  import { thumbUrl } from '$lib/api';
  import { Icon } from '@immich/ui';
  import { mdiPlayCircleOutline } from '@mdi/js';

  type Props = { id: string; video?: boolean; class?: string; size?: 'thumbnail' | 'preview'; alt?: string };
  const { id, video = false, class: className = '', size = 'thumbnail', alt = '' }: Props = $props();
  let failed = $state(false);
</script>

<div class="relative overflow-hidden bg-gray-200 dark:bg-gray-800 {className}">
  {#if !failed}
    <img
      src={thumbUrl(id, size)}
      {alt}
      loading="lazy"
      class="size-full object-cover"
      onerror={() => (failed = true)}
    />
  {/if}
  {#if video}
    <span class="absolute end-1.5 top-1.5 text-white drop-shadow">
      <Icon icon={mdiPlayCircleOutline} size="1.4em" />
    </span>
  {/if}
</div>
