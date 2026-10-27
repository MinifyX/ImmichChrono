<script lang="ts">
  import type { Suggestion } from '$lib/api';
  import { confidenceColor, formatDate, formatShift, percent, SOURCE_LABELS, STATUS_LABELS } from '$lib/format';
  import { Badge, Checkbox, Text } from '@immich/ui';
  import AssetThumb from './AssetThumb.svelte';

  type Props = {
    suggestion: Suggestion;
    selected?: boolean;
    selectable?: boolean;
    onToggle?: () => void;
    onOpen?: () => void;
  };
  const { suggestion: s, selected = false, selectable = true, onToggle, onOpen }: Props = $props();
  const before = $derived(s.previous_date ?? s.asset.localDateTime);
</script>

<div
  class="flex overflow-hidden rounded-2xl border bg-subtle transition-colors {selected
    ? 'border-primary ring-2 ring-primary/40'
    : 'border-light-200 dark:border-light-300'}"
>
  <button type="button" class="relative block w-32 shrink-0 cursor-zoom-in sm:w-40" onclick={onOpen} aria-label="Details öffnen">
    <AssetThumb id={s.asset.id} video={s.asset.type === 'VIDEO'} class="size-full min-h-32" alt={s.asset.fileName} />
  </button>
  <div class="flex min-w-0 grow flex-col gap-1.5 p-3">
    <div class="flex items-start gap-2">
      <Text size="small" fontWeight="semi-bold" class="grow truncate" title={s.asset.path}>{s.asset.fileName}</Text>
      {#if selectable}
        <Checkbox checked={selected} onCheckedChange={() => onToggle?.()} aria-label="Auswählen" />
      {/if}
    </div>
    <div class="grid grid-cols-[auto_1fr] items-baseline gap-x-2 text-sm">
      <span class="text-gray-500 dark:text-gray-400">Bisher</span>
      <span class="line-through decoration-danger/60">{formatDate(before)}</span>
      <span class="text-gray-500 dark:text-gray-400">Neu</span>
      <span class="font-semibold text-primary">{formatDate(s.proposed, s.precision)}</span>
    </div>
    <div class="flex flex-wrap items-center gap-1.5">
      <Badge size="tiny" color="secondary">{SOURCE_LABELS[s.source] ?? s.source}</Badge>
      <Badge size="tiny" color={confidenceColor(s.confidence)}>{percent(s.confidence)}</Badge>
      <Badge size="tiny" color="info">{formatShift(before, s.proposed)}</Badge>
      {#if s.status !== 'pending'}
        <Badge size="tiny" color={s.status === 'reverted' ? 'warning' : 'success'}>{STATUS_LABELS[s.status] ?? s.status}</Badge>
      {/if}
    </div>
    <Text size="tiny" color="muted" class="line-clamp-2" title={s.explanation}>{s.explanation}</Text>
  </div>
</div>
