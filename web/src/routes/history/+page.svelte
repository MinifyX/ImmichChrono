<script lang="ts">
  import { api, qs, type Page, type Reason, type Suggestion } from '$lib/api';
  import AssetModal from '$lib/components/AssetModal.svelte';
  import PageHeader from '$lib/components/PageHeader.svelte';
  import ReasonModal from '$lib/components/ReasonModal.svelte';
  import SuggestionCard from '$lib/components/SuggestionCard.svelte';
  import { formatTimestamp } from '$lib/format';
  import { app } from '$lib/state.svelte';
  import { Alert, Button, Input, Text, toastManager } from '@immich/ui';
  import { mdiUndo } from '@mdi/js';

  let data = $state<Page<Suggestion> | null>(null);
  let q = $state('');
  let pageNo = $state(1);
  let detail = $state<string | null>(null);
  let busy = $state<number | null>(null);
  let ask = $state<number | null>(null);

  async function load() {
    data = await api<Page<Suggestion>>(`/suggestions${qs({ status: 'history', q, page: pageNo })}`);
  }
  $effect(() => {
    void app.generation;
    void [q, pageNo];
    load();
  });

  async function undo(id: number, why: Reason | null) {
    ask = null;
    if (!why) return;
    busy = id;
    try {
      await api(`/suggestions/${id}/undo`, { body: why });
      toastManager.success('Änderung zurückgenommen');
      await load();
    } catch (e) {
      toastManager.danger((e as Error).message);
    } finally {
      busy = null;
    }
  }
  const pages = $derived(data ? Math.max(1, Math.ceil(data.total / data.size)) : 1);
</script>

<PageHeader title="Verlauf" description="Alle übernommenen Änderungen. Rückgängig setzt das vorherige Datum in Immich wieder ein.">
  {#snippet actions()}
    <div class="w-64"><Input placeholder="Suche…" bind:value={q} oninput={() => (pageNo = 1)} /></div>
  {/snippet}
</PageHeader>

{#if data && data.items.length === 0}
  <Alert color="info">Noch keine Änderungen.</Alert>
{:else if data}
  <div class="grid gap-3 md:grid-cols-2 2xl:grid-cols-3">
    {#each data.items as s (s.id)}
      <div class="flex flex-col gap-1">
        <SuggestionCard suggestion={s} selectable={false} onOpen={() => (detail = s.asset.id)} />
        <div class="flex items-center justify-between px-2">
          <Text size="tiny" color="muted">{s.applied_at ? formatTimestamp(s.applied_at) : ''}</Text>
          {#if s.status !== 'reverted'}
            <Button size="tiny" variant="ghost" color="secondary" leadingIcon={mdiUndo} loading={busy === s.id} onclick={() => (ask = s.id)}>
              Rückgängig
            </Button>
          {/if}
        </div>
      </div>
    {/each}
  </div>
  {#if pages > 1}
    <div class="mt-6 flex items-center justify-center gap-3">
      <Button size="small" variant="ghost" disabled={pageNo <= 1} onclick={() => pageNo--}>Zurück</Button>
      <Text size="small">Seite {pageNo} von {pages}</Text>
      <Button size="small" variant="ghost" disabled={pageNo >= pages} onclick={() => pageNo++}>Weiter</Button>
    </div>
  {/if}
{/if}

{#if detail}
  <AssetModal id={detail} onClose={() => (detail = null)} onChange={load} />
{/if}

{#if ask !== null}
  <ReasonModal action="reverted" title="Änderung zurücknehmen" confirmText="Rückgängig" onClose={(why) => undo(ask!, why)} />
{/if}
