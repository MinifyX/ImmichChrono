<script lang="ts">
  import { api } from '$lib/api';
  import { PHASE_LABELS } from '$lib/format';
  import { app } from '$lib/state.svelte';
  import { Button, Card, CardBody, LoadingSpinner, ProgressBar, Text } from '@immich/ui';

  const job = $derived(app.job);
  const progress = $derived(job?.total ? (job.progress ?? 0) / job.total : undefined);

  async function cancel() {
    if (job) await api(`/jobs/${job.id}/cancel`, { method: 'POST' });
  }
</script>

{#if job?.status === 'running'}
  <Card color="secondary" class="mb-4">
    <CardBody>
      <div class="flex items-center gap-3">
        <LoadingSpinner />
        <div class="grow">
          <Text fontWeight="semi-bold">
            {job.kind === 'claude' ? 'Claude-Analyse läuft' : 'Scan läuft'} – {PHASE_LABELS[job.phase ?? ''] ?? job.phase}
          </Text>
          <Text size="small" color="muted">
            {#if job.total}{job.progress ?? 0} / {job.total}{/if}
            {#if job.message}· {job.message}{/if}
          </Text>
        </div>
        <Button size="small" variant="ghost" color="danger" onclick={cancel}>Abbrechen</Button>
      </div>
      {#if progress !== undefined}
        <ProgressBar progress={progress} class="mt-3" />
      {/if}
    </CardBody>
  </Card>
{/if}
