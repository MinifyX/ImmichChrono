<script lang="ts">
  import type { AssetView } from '$lib/api';
  import { formatDate } from '$lib/format';
  import { app } from '$lib/state.svelte';
  import { Checkbox } from '@immich/ui';
  import AssetThumb from './AssetThumb.svelte';

  type Props = { asset: AssetView; selected?: boolean; onToggle?: () => void; onOpen?: () => void };
  const { asset, selected = false, onToggle, onOpen }: Props = $props();
</script>

<div class="group relative overflow-hidden rounded-xl {selected ? 'ring-4 ring-primary' : ''}">
  <button type="button" class="block aspect-square w-full" onclick={onOpen} aria-label="Details zu {asset.fileName}">
    <AssetThumb id={asset.id} video={asset.type === 'VIDEO'} class="size-full" alt={asset.fileName} />
  </button>
  <div class="absolute start-2 top-2 rounded bg-white/80 p-0.5 dark:bg-black/60">
    <Checkbox checked={selected} onCheckedChange={() => onToggle?.()} aria-label="Auswählen" size="small" />
  </div>
  <div class="pointer-events-none absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/80 to-transparent p-2 text-xs text-white">
    <div class="truncate font-medium">{asset.fileName}</div>
    <div class="opacity-80">{formatDate(asset.localDateTime)}</div>
    <div class="truncate opacity-70">{asset.issues.map((i) => app.issueLabel(i)).join(' · ')}</div>
  </div>
</div>
