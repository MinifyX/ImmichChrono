<script lang="ts">
  import { api, ApiError, type Estimate, type Job } from '$lib/api';
  import { usd } from '$lib/format';
  import { app } from '$lib/state.svelte';
  import { Alert, Button, Field, Input, Modal, ModalBody, ModalFooter, Select, Text, toastManager } from '@immich/ui';
  import { mdiCreation } from '@mdi/js';

  type Props = { assetIds: string[]; onClose: () => void };
  const { assetIds, onClose }: Props = $props();

  const models = $derived(app.server?.claude.models ?? []);
  let model = $state(app.server?.claude.defaultModel ?? '');
  let budget = $state('1');
  let estimate = $state<Estimate | null>(null);
  let error = $state('');
  let busy = $state(false);

  api<{ claude_budget_usd: number; claude_model: string | null }>('/settings').then((s) => {
    budget = String(s.claude_budget_usd);
    if (s.claude_model) model = s.claude_model;
  });

  $effect(() => {
    const body = { asset_ids: assetIds, model, budget_usd: Number(budget) || 0 };
    api<Estimate>('/claude/estimate', { body })
      .then((e) => ((estimate = e), (error = '')))
      .catch((e: ApiError) => (error = e.message));
  });

  async function start() {
    busy = true;
    try {
      const job = await api<Job>('/claude/runs', { body: { asset_ids: assetIds, model, budget_usd: Number(budget) } });
      app.watch(job);
      toastManager.info('Claude-Analyse gestartet');
      onClose();
    } catch (e) {
      error = (e as Error).message;
    } finally {
      busy = false;
    }
  }
</script>

<Modal title="Mit Claude analysieren" icon={mdiCreation} {onClose} size="medium">
  <ModalBody>
    <div class="flex flex-col gap-4">
      <Text>
        {assetIds.length} {assetIds.length === 1 ? 'Datei wird' : 'Dateien werden'} als verkleinerte Vorschau mit Kontext
        (Dateiname, Ordner, OCR-Text, Nachbarbilder) an die Claude-API geschickt. Die Ergebnisse landen als Vorschlag in der
        Prüfung.
      </Text>
      {#if !app.server?.claude.configured}
        <Alert color="warning" title="Kein API-Schlüssel">Setze ANTHROPIC_API_KEY im Container, um Claude zu nutzen.</Alert>
      {/if}
      <div class="grid gap-4 sm:grid-cols-2">
        <Field label="Modell">
          <Select options={models.map((m) => ({ label: m, value: m }))} bind:value={model} />
        </Field>
        <Field label="Budget für diesen Lauf (USD)" description="Der Lauf stoppt, bevor das Budget überschritten würde.">
          <Input type="number" min="0" max="100" step="0.1" bind:value={budget} />
        </Field>
      </div>
      {#if estimate}
        <div class="rounded-xl bg-subtle p-4 text-sm">
          <div class="flex justify-between"><span>Pro Bild (geschätzt)</span><span>{usd(estimate.per_image_usd)}</span></div>
          <div class="flex justify-between"><span>Pro Bild (Obergrenze)</span><span>{usd(estimate.max_per_image_usd)}</span></div>
          <div class="mt-2 flex justify-between font-semibold">
            <span>Gesamt (geschätzt)</span><span>{usd(estimate.total_usd)}</span>
          </div>
        </div>
        {#if !estimate.fits_budget}
          <Alert color="warning">
            Die Schätzung liegt über dem Budget – es werden nur so viele Dateien analysiert, wie das Budget erlaubt.
          </Alert>
        {/if}
      {/if}
      {#if error}<Alert color="danger">{error}</Alert>{/if}
    </div>
  </ModalBody>
  <ModalFooter>
    <div class="flex w-full justify-end gap-2">
      <Button variant="ghost" color="secondary" onclick={onClose}>Abbrechen</Button>
      <Button
        leadingIcon={mdiCreation}
        loading={busy}
        disabled={!app.server?.claude.configured || !estimate || Number(budget) <= 0}
        onclick={start}
      >
        Analyse starten
      </Button>
    </div>
  </ModalFooter>
</Modal>
