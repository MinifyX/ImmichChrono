<script lang="ts">
  import { Heading, Text } from '@immich/ui';
  import type { Snippet } from 'svelte';

  type Props = { title: string; description?: string; actions?: Snippet };
  const { title, description, actions }: Props = $props();
</script>

<div class="mb-6 flex flex-wrap items-end justify-between gap-4">
  <div>
    <Heading size="large" tag="h1">{title}</Heading>
    {#if description}<Text color="muted" class="mt-1 max-w-3xl">{description}</Text>{/if}
  </div>
  {#if actions}<div class="flex flex-wrap items-center gap-2">{@render actions()}</div>{/if}
</div>
