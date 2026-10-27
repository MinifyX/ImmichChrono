<script lang="ts">
  import { goto } from '$app/navigation';
  import { api, type User } from '$lib/api';
  import { app } from '$lib/state.svelte';
  import { Alert, Button, Card, CardBody, Field, Heading, Input, Logo, PasswordInput, Text } from '@immich/ui';

  let email = $state('');
  let password = $state('');
  let error = $state('');
  let busy = $state(false);

  async function login(event: SubmitEvent) {
    event.preventDefault();
    busy = true;
    error = '';
    try {
      app.user = await api<User>('/auth/login', { body: { email, password } });
      await app.refreshJob();
      await goto('/');
    } catch (e) {
      error = (e as Error).message;
    } finally {
      busy = false;
    }
  }
</script>

<div class="flex min-h-dvh items-center justify-center bg-light p-4">
  <Card class="w-full max-w-md">
    <CardBody>
      <form class="flex flex-col gap-5 p-4" onsubmit={login}>
        <div class="flex flex-col items-center gap-3">
          <Logo variant="icon" size="giant" />
          <Heading size="large" class="text-primary">ImmichChrono</Heading>
          <Text color="muted" class="text-center">Mit deinem Immich-Konto anmelden</Text>
        </div>
        {#if error}<Alert color="danger">{error}</Alert>{/if}
        <Field label="E-Mail" required>
          <Input type="email" autocomplete="username" bind:value={email} />
        </Field>
        <Field label="Passwort" required>
          <PasswordInput autocomplete="current-password" bind:value={password} />
        </Field>
        <Button type="submit" fullWidth loading={busy} disabled={!email || !password}>Anmelden</Button>
        {#if app.server}
          <Text size="tiny" color="muted" class="text-center">Server: {app.server.immichUrl}</Text>
        {/if}
      </form>
    </CardBody>
  </Card>
</div>
