import { HttpClient } from '@angular/common/http';
import { Injectable, inject, signal } from '@angular/core';
import { firstValueFrom, of } from 'rxjs';
import { catchError } from 'rxjs/operators';
import { environment } from '../../../../../environments/environment';
import { AgentMetadata } from '../models/agent-metadata.model';

/**
 * Fetches and caches the list of available analytical / transactional agents
 * from `GET /api/agents/metadata`. Failures are swallowed so the chat UI keeps
 * working even when the backend doesn't expose the new endpoint yet.
 */
@Injectable({ providedIn: 'root' })
export class AgentsMetadataService {
  private readonly http = inject(HttpClient);
  private readonly url = `${environment.apiUrl}api/agents/metadata`;

  /** Cached list (never throws). */
  readonly agents = signal<AgentMetadata[]>([]);

  /** Whether we've attempted the fetch — so callers can avoid re-firing. */
  readonly loaded = signal(false);

  /** Lazy load — safe to call multiple times. */
  async load(): Promise<AgentMetadata[]> {
    if (this.loaded()) return this.agents();

    try {
      const res = await firstValueFrom(
        this.http
          .get<{ agents: AgentMetadata[] }>(this.url)
          .pipe(catchError(() => of({ agents: [] as AgentMetadata[] }))),
      );
      const list = (res?.agents ?? []).filter((a) => !!a && a.enabled);
      this.agents.set(list);
    } catch {
      this.agents.set([]);
    } finally {
      this.loaded.set(true);
    }
    return this.agents();
  }

  /** Lookup helper. */
  byName(name: string | null | undefined): AgentMetadata | undefined {
    if (!name) return undefined;
    return this.agents().find((a) => a.name === name);
  }
}
