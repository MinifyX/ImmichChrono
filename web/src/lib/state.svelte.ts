import { api, type Job, type ServerInfo, type User } from './api';

class AppState {
  user = $state<User | null>(null);
  server = $state<ServerInfo | null>(null);
  job = $state<Job | null>(null);
  /** Increments whenever a job finishes so pages can reload their data. */
  generation = $state(0);
  #timer: ReturnType<typeof setTimeout> | undefined;

  async loadServer() {
    this.server = await api<ServerInfo>('/server');
  }

  issueLabel(issue: string) {
    return this.server?.issueLabels[issue] ?? issue;
  }

  async refreshJob(jobId?: string) {
    clearTimeout(this.#timer);
    const id = jobId ?? this.job?.id;
    if (!id) {
      const scans = await api<Job[]>('/scans');
      const running = scans.find((j) => j.status === 'running');
      if (!running) return;
      this.job = running;
    } else {
      const wasRunning = this.job?.status === 'running' || this.job?.id !== id;
      this.job = await api<Job>(`/jobs/${id}`);
      if (wasRunning && this.job.status !== 'running') this.generation++;
    }
    if (this.job?.status === 'running') this.#timer = setTimeout(() => this.refreshJob(), 1500);
  }

  watch(job: Job) {
    this.job = job;
    this.#timer = setTimeout(() => this.refreshJob(job.id), 800);
  }

  stop() {
    clearTimeout(this.#timer);
  }
}

export const app = new AppState();
