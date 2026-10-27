<script lang="ts">
  import { api, type Settings } from '$lib/api';
  import PageHeader from '$lib/components/PageHeader.svelte';
  import { usd } from '$lib/format';
  import { app } from '$lib/state.svelte';
  import {
    Alert,
    Badge,
    Button,
    Card,
    CardBody,
    CardDescription,
    CardHeader,
    CardTitle,
    Field,
    Input,
    Select,
    Switch,
    Text,
    toastManager,
  } from '@immich/ui';
  import { mdiContentSave } from '@mdi/js';

  let settings = $state<Settings | null>(null);
  let budget = $state('1');
  let ollamaMax = $state('200');
  let usage = $state<{ total_usd: number; month_usd: number; calls: number } | null>(null);
  let busy = $state(false);

  $effect(() => {
    api<Settings>('/settings').then((s) => {
      settings = s;
      budget = String(s.claude_budget_usd);
      ollamaMax = String(s.ollama_max_per_scan);
    });
    api<typeof usage>('/claude/usage').then((u) => (usage = u));
  });

  async function save() {
    if (!settings) return;
    busy = true;
    try {
      settings = await api<Settings>('/settings', {
        method: 'PUT',
        body: { ...settings, claude_budget_usd: Number(budget), ollama_max_per_scan: Number(ollamaMax) },
      });
      toastManager.success('Einstellungen gespeichert');
    } catch (e) {
      toastManager.danger((e as Error).message);
    } finally {
      busy = false;
    }
  }

  const claude = $derived(app.server?.claude);
  const ollama = $derived(app.server?.ollama);
</script>

<PageHeader title="Einstellungen">
  {#snippet actions()}
    <Button leadingIcon={mdiContentSave} loading={busy} disabled={!settings} onclick={save}>Speichern</Button>
  {/snippet}
</PageHeader>

{#if settings}
  <div class="grid max-w-5xl gap-6 lg:grid-cols-2">
    <Card>
      <CardHeader>
        <CardTitle>Automatik</CardTitle>
        <CardDescription>Nur eindeutige Fälle: GPS-Zeitstempel, unmissverständlicher Dateiname (z. B. Screenshots), exakte Duplikate mit korrektem Datum.</CardDescription>
      </CardHeader>
      <CardBody>
        <div class="flex items-center justify-between gap-4">
          <Text>Sichere Fälle beim Scan automatisch übernehmen</Text>
          <Switch bind:checked={settings.auto_apply} />
        </div>
      </CardBody>
    </Card>

    <Card>
      <CardHeader>
        <CardTitle>Lokale KI (Ollama)</CardTitle>
        <CardDescription>Läuft beim Scan für Dateien ohne andere Hinweise. Bleibt komplett lokal.</CardDescription>
      </CardHeader>
      <CardBody>
        <div class="flex flex-col gap-4">
          <div class="flex flex-wrap gap-2">
            {#if !ollama?.configured}
              <Badge color="secondary">Nicht konfiguriert (OLLAMA_URL)</Badge>
            {:else if !ollama.reachable}
              <Badge color="danger">Nicht erreichbar</Badge>
            {:else if !ollama.installed}
              <Badge color="warning">Modell {ollama.model} fehlt</Badge>
            {:else}
              <Badge color="success">Bereit · {ollama.model}</Badge>
            {/if}
          </div>
          {#if ollama?.error}<Text size="tiny" color="muted">{ollama.error}</Text>{/if}
          <div class="flex items-center justify-between gap-4">
            <Text>Beim Scan verwenden</Text>
            <Switch bind:checked={settings.ollama_enabled} disabled={!ollama?.configured} />
          </div>
          <Field label="Maximal Dateien pro Scan" description="Ohne GPU dauert ein Bild einige Sekunden.">
            <Input type="number" min="0" max="20000" bind:value={ollamaMax} />
          </Field>
        </div>
      </CardBody>
    </Card>

    <Card>
      <CardHeader>
        <CardTitle>Claude</CardTitle>
        <CardDescription>Nur auf Knopfdruck für ausgewählte Dateien. Vor jedem Lauf siehst du eine Kostenschätzung.</CardDescription>
      </CardHeader>
      <CardBody>
        <div class="flex flex-col gap-4">
          {#if !claude?.configured}
            <Alert color="warning">Kein API-Schlüssel gesetzt (ANTHROPIC_API_KEY).</Alert>
          {/if}
          <Field label="Standardmodell">
            <Select
              options={(claude?.models ?? []).map((m) => {
                const p = claude?.prices[m];
                return { value: m, label: p ? `${m} (${p[0]} $ / ${p[1]} $ pro Mio. Token)` : m };
              })}
              value={settings.claude_model ?? claude?.defaultModel ?? ''}
              onChange={(v) => (settings!.claude_model = String(v))}
            />
          </Field>
          <Field label="Standardbudget pro Lauf (USD)">
            <Input type="number" min="0" max="100" step="0.1" bind:value={budget} />
          </Field>
          {#if usage}
            <div class="flex flex-wrap gap-x-6 text-sm text-gray-500 dark:text-gray-400">
              <span>Diesen Monat: {usd(usage.month_usd)}</span>
              <span>Gesamt: {usd(usage.total_usd)}</span>
              <span>Anfragen: {usage.calls}</span>
            </div>
          {/if}
        </div>
      </CardBody>
    </Card>

    <Card>
      <CardHeader><CardTitle>Verbindung</CardTitle></CardHeader>
      <CardBody>
        <dl class="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
          <dt class="text-gray-500">Immich</dt><dd class="break-all">{app.server?.immichUrl} (v{app.server?.immichVersion ?? '?'})</dd>
          <dt class="text-gray-500">Standardzeitzone</dt><dd>{app.server?.defaultTimeZone}</dd>
          <dt class="text-gray-500">ImmichChrono</dt><dd>v{app.server?.version}</dd>
        </dl>
      </CardBody>
    </Card>
  </div>
{/if}
