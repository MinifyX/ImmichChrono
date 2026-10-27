<script lang="ts">
  import { api, type AssetDetail, type DecisionAction, type Reason } from '$lib/api';
  import {
    confidenceColor,
    formatDate,
    formatTimestamp,
    percent,
    SOURCE_LABELS,
    STATUS_LABELS,
    toInputValue,
  } from '$lib/format';
  import { app } from '$lib/state.svelte';
  import { Alert, Badge, Button, Field, Input, LoadingSpinner, Modal, ModalBody, Text, toastManager } from '@immich/ui';
  import { mdiCalendarEdit, mdiCheck, mdiClose, mdiCreation, mdiOpenInNew, mdiUndo } from '@mdi/js';
  import AssetThumb from './AssetThumb.svelte';
  import ClaudeModal from './ClaudeModal.svelte';
  import ReasonModal from './ReasonModal.svelte';

  type Props = { id: string; onClose: () => void; onChange?: () => void };
  const { id, onClose, onChange }: Props = $props();

  let asset = $state<AssetDetail | null>(null);
  let error = $state('');
  let manual = $state('');
  let busy = $state(false);
  let claudeOpen = $state(false);
  let ask = $state<{ action: DecisionAction; sid?: number } | null>(null);

  async function load() {
    try {
      asset = await api<AssetDetail>(`/assets/${id}`);
      manual = toInputValue(asset.localDateTime);
    } catch (e) {
      error = (e as Error).message;
    }
  }
  $effect(() => void load());

  async function act(fn: () => Promise<unknown>, ok: string) {
    busy = true;
    try {
      await fn();
      toastManager.success(ok);
      await load();
      onChange?.();
    } catch (e) {
      toastManager.danger((e as Error).message);
    } finally {
      busy = false;
    }
  }

  const ASK = {
    applied: { title: 'Vorschlag übernehmen', confirm: 'Übernehmen' },
    rejected: { title: 'Vorschlag ablehnen', confirm: 'Ablehnen' },
    reverted: { title: 'Änderung zurücknehmen', confirm: 'Rückgängig' },
    manual: { title: 'Datum manuell setzen', confirm: 'Setzen' },
  } as const;

  function decide(why: Reason | null) {
    const a = ask;
    ask = null;
    if (!a || !why) return;
    const sid = a.sid!;
    if (a.action === 'applied') act(() => api('/suggestions/apply', { body: { ids: [sid], ...why } }), 'Datum übernommen');
    else if (a.action === 'rejected') act(() => api('/suggestions/reject', { body: { ids: [sid], ...why } }), 'Vorschlag abgelehnt');
    else if (a.action === 'reverted') act(() => api(`/suggestions/${sid}/undo`, { body: why }), 'Änderung zurückgenommen');
    else
      act(
        () => api(`/assets/${id}/manual`, { body: { date: manual.length === 16 ? `${manual}:00` : manual, ...why } }),
        'Datum gesetzt',
      );
  }
</script>

<Modal title={asset?.fileName ?? 'Datei'} {onClose} size="giant">
  <ModalBody>
    {#if error}
      <Alert color="danger">{error}</Alert>
    {:else if !asset}
      <div class="flex justify-center p-10"><LoadingSpinner size="large" /></div>
    {:else}
      <div class="grid gap-6 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
        <AssetThumb id={asset.id} size="preview" video={asset.type === 'VIDEO'} class="max-h-[70vh] rounded-xl [&_img]:object-contain" />
        <div class="flex flex-col gap-4">
          <dl class="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-sm">
            <dt class="text-gray-500">Aktuell</dt><dd class="font-semibold">{formatDate(asset.localDateTime)} {asset.timeZone ?? ''}</dd>
            <dt class="text-gray-500">Pfad</dt><dd class="break-all">{asset.path}</dd>
            <dt class="text-gray-500">Kamera</dt><dd>{[asset.make, asset.model].filter(Boolean).join(' ') || '–'}</dd>
            <dt class="text-gray-500">Ort</dt><dd>{[asset.city, asset.country].filter(Boolean).join(', ') || '–'}</dd>
            <dt class="text-gray-500">Datei erstellt</dt><dd>{formatTimestamp(asset.fileCreatedAt)}</dd>
            <dt class="text-gray-500">Hochgeladen</dt><dd>{formatTimestamp(asset.uploadedAt)}</dd>
            {#if asset.people.length}
              <dt class="text-gray-500">Personen</dt><dd>{asset.people.map((p) => p.name).join(', ')}</dd>
            {/if}
          </dl>
          {#if asset.issues.length}
            <div class="flex flex-wrap gap-1.5">
              {#each asset.issues as issue (issue)}<Badge size="small" color="warning">{app.issueLabel(issue)}</Badge>{/each}
            </div>
          {/if}

          <div>
            <Text fontWeight="semi-bold" class="mb-2">Vorschläge</Text>
            {#if asset.suggestions.length === 0}
              <Text size="small" color="muted">Keine Vorschläge gefunden.</Text>
            {/if}
            <div class="flex flex-col gap-2">
              {#each asset.suggestions as s (s.id)}
                <div class="rounded-xl border border-light-200 p-3 text-sm dark:border-light-300">
                  <div class="flex flex-wrap items-center gap-1.5">
                    <span class="font-semibold">{formatDate(s.proposed, s.precision)}</span>
                    <Badge size="tiny" color="secondary">{SOURCE_LABELS[s.source] ?? s.source}</Badge>
                    <Badge size="tiny" color={confidenceColor(s.confidence)}>{percent(s.confidence)}</Badge>
                    <Badge size="tiny" color="info">{STATUS_LABELS[s.status] ?? s.status}</Badge>
                    <span class="grow"></span>
                    {#if s.status === 'pending'}
                      <Button size="tiny" variant="outline" color="danger" leadingIcon={mdiClose} disabled={busy}
                        onclick={() => (ask = { action: 'rejected', sid: s.id })}>Ablehnen</Button>
                      <Button size="tiny" leadingIcon={mdiCheck} disabled={busy} onclick={() => (ask = { action: 'applied', sid: s.id })}>
                        Übernehmen
                      </Button>
                    {:else if s.status === 'applied' || s.status === 'auto_applied'}
                      <Button size="tiny" variant="outline" color="secondary" leadingIcon={mdiUndo} disabled={busy}
                        onclick={() => (ask = { action: 'reverted', sid: s.id })}>
                        Rückgängig
                      </Button>
                    {/if}
                  </div>
                  <Text size="tiny" color="muted" class="mt-1">{s.explanation}</Text>
                </div>
              {/each}
            </div>
          </div>

          <div class="rounded-xl bg-subtle p-3">
            <Field label="Datum manuell setzen" description="Ortszeit. Die Zeitzone wird vom Bild bzw. der Standardzone übernommen.">
              <Input type="datetime-local" step="1" bind:value={manual} />
            </Field>
            <div class="mt-3 flex flex-wrap gap-2">
              <Button size="small" leadingIcon={mdiCalendarEdit} disabled={busy || !manual} onclick={() => (ask = { action: 'manual' })}>Setzen</Button>
              <Button size="small" variant="outline" leadingIcon={mdiCreation} onclick={() => (claudeOpen = true)}>
                Claude fragen
              </Button>
              <Button size="small" variant="ghost" color="secondary" leadingIcon={mdiOpenInNew} href={asset.immichLink} target="_blank">
                In Immich öffnen
              </Button>
            </div>
          </div>
        </div>
      </div>
    {/if}
  </ModalBody>
</Modal>

{#if claudeOpen}
  <ClaudeModal assetIds={[id]} onClose={() => (claudeOpen = false)} />
{/if}

{#if ask}
  <ReasonModal action={ask.action} title={ASK[ask.action].title} confirmText={ASK[ask.action].confirm}
    danger={ask.action === 'rejected'} onClose={decide} />
{/if}
