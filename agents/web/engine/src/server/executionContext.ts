import { AsyncLocalStorage } from 'node:async_hooks';
import { createHash, timingSafeEqual } from 'node:crypto';

export interface ExecutionContext {
  context_version: 1;
  principal_id: string; workspace_id: string; device_id: string;
  operation_id: string; request_id: string; trace_id: string;
  expires_at: number; effective_access: 'read' | 'write';
  effective_resources: Array<{resource_id: string; kind: string; [key: string]: unknown}>;
  [key: string]: unknown;
}
export const executionContext = new AsyncLocalStorage<ExecutionContext>();
export const internalTransport = new AsyncLocalStorage<boolean>();

export function authenticateInternalToken(value: unknown): boolean {
  const key = Buffer.from(process.env.ZAGENT_INTERNAL_TOKEN ?? '', 'utf8');
  const supplied = typeof value === 'string' ? Buffer.from(value, 'utf8') : Buffer.alloc(0);
  return key.length >= 32 && supplied.length === key.length && timingSafeEqual(key, supplied);
}

/** Authority exists only within an authenticated private HTTP request. */
export function verifyExecutionContext(tool: string, args: unknown, extra: any): ExecutionContext {
  if (internalTransport.getStore() !== true) throw new Error('AUTHENTICATED_INTERNAL_CHANNEL_REQUIRED');
  const ctx = extra?._meta?.['zagent.execution_context'];
  if (!ctx || typeof ctx !== 'object') throw new Error('AUTHENTICATED_EXECUTION_CONTEXT_REQUIRED');
  if (ctx.context_version !== 1) throw new Error('UNSUPPORTED_CONTEXT_VERSION');
  for (const field of ['principal_id','workspace_id','device_id','operation_id','request_id','trace_id']) {
    if (typeof ctx[field] !== 'string' || !ctx[field].trim() || ctx[field].length > 256) throw new Error('INVALID_CONTEXT_ID');
  }
  const now = Date.now()/1000;
  if (typeof ctx.deadline !== 'number' || !Number.isFinite(ctx.deadline) || !(now < ctx.deadline && ctx.deadline <= now+3600)) throw new Error('CONTEXT_EXPIRED_OR_INVALID');
  if (!process.env.ZAGENT_DEVICE_ID || ctx.device_id !== process.env.ZAGENT_DEVICE_ID) throw new Error('IDENTITY_MISMATCH_OR_DEVICE_NOT_CONFIGURED');
  if (!['read','write'].includes(ctx.effective_access)) throw new Error('INVALID_ACCESS_SCOPE');
  if (!Array.isArray(ctx.effective_resources) || !ctx.effective_resources.length || ctx.effective_resources.length > 128 || ctx.effective_resources.some((r: any) => !r || typeof r.resource_id !== 'string' || !r.resource_id || typeof r.kind !== 'string' || !r.kind)) throw new Error('RESOURCE_SCOPE_REQUIRED');
  return {...ctx, expires_at: ctx.deadline} as ExecutionContext;
}

export function artifactOwner(ctx: ExecutionContext): string {
  return createHash('sha256').update(JSON.stringify([ctx.principal_id, ctx.workspace_id])).digest('hex');
}

/** Native browser cookies are shared: conservatively one immutable owner per
 * process, including after detach/revoke. Core must restart/reprovision to rebind. */
export class BrowserResourceOwner {
  private owner: string | null = null;
  claim(ctx: ExecutionContext): void {
    const resources = ctx.effective_resources.filter(r => r.kind === 'browser' || r.kind === 'web');
    if (resources.length !== 1) throw new Error('ONE_BROWSER_RESOURCE_REQUIRED');
    const identity = JSON.stringify([ctx.principal_id, ctx.workspace_id, resources[0]!.resource_id]);
    if (this.owner !== null && identity !== this.owner) throw new Error('BROWSER_RESOURCE_ALREADY_OWNED');
    this.owner = identity;
  }
}

const browserOwner = new BrowserResourceOwner();
// Explicit observation set; unknown tools require write instead of trusting name prefixes.
const READ_TOOLS = new Set(`web_ping web_browser_status web_runtime_info web_bridge_status web_bridge_pair_status web_bridge_tabs web_tabs web_get_url web_get_title web_get_page_state web_get_html web_inspect web_get_text web_get_elements web_get_element web_get_attribute web_get_bounds web_get_accessibility_tree web_find web_find_text web_find_role web_visual_latest web_visual_list web_visual_store_status web_chrome_profiles`.split(/\s+/));

export function installExecutionGate(server: any): void {
  const register = server.registerTool.bind(server);
  server.registerTool = (name: string, config: unknown, callback: (...args: any[]) => any) =>
    register(name, config, (args: unknown, extra: any) => {
      const ctx = verifyExecutionContext(name, args, extra);
      if (!READ_TOOLS.has(name) && ctx.effective_access !== 'write') throw new Error('WRITE_SCOPE_REQUIRED');
      browserOwner.claim(ctx);
      return executionContext.run(ctx, () => callback(args, extra));
    });
}
