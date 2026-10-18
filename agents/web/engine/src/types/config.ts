export type BrowserName = "chrome";
export type SessionIsolationMode = "auto" | "context" | "tabs";
export type RuntimeMode = "native_attach" | "managed";

export interface Viewport {
  width: number;
  height: number;
}

export interface ZagentWebSettings {
  host: string;
  port: number;
  browser: BrowserName;
  headless: boolean;
  autoStartBrowser?: boolean;
  autoRestartBrowser?: boolean;
  runtimeMode?: RuntimeMode;
  nativeAutoAttach?: boolean;
  nativeAttachOnDemand?: boolean;
  chromeExecutablePath?: string;
  sessionIsolationMode?: SessionIsolationMode;
  sessionInheritProfileState?: boolean;
  cdpEndpoint?: string;
  defaultViewport: Viewport;
  allowedHosts: string[];
  allowExternalHosts: boolean;
  navigationTimeoutMs: number;
  actionTimeoutMs: number;
  screenshotsDir: string;
  downloadsDir: string;
  tracesDir: string;
  harDir: string;
  recordingsDir: string;
  videosDir: string;
  logsDir: string;
  enableJavascriptEvaluation: boolean;
  enableNetworkInterception: boolean;
  maxNetworkEvents: number;
  maxConsoleEvents: number;
  redactHeaders: string[];
}

export interface WebTarget {
  name: string;
  url: string;
  description?: string;
  enabled?: boolean;
}