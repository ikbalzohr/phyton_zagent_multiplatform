import type { McpServer } from "@modelcontextprotocol/server";
import { registerRuntimeTools } from "./runtime.js";
import { registerNavigationTools } from "./navigation.js";
import { registerInspectionTools } from "./inspection.js";
import { registerInteractionTools } from "./interaction.js";
import { registerTabDialogTools } from "./tabsDialogs.js";
import { registerNetworkTools } from "./network.js";
import { registerStateTools } from "./state.js";
import { registerTestingTools } from "./testing.js";
import { registerAdvancedTools } from "./advanced.js";
import { registerTargetSecurityTools } from "./targetsSecurity.js";
import { registerOrchestrationTools } from "./orchestration.js";
import { registerNativeChromeTools } from "./nativeChrome.js";
import { registerBridgeTools } from './bridge.js';
import { registerVisualTools } from "./visual.js";

export function registerAllTools(server: McpServer): void {
  registerRuntimeTools(server);
  registerNavigationTools(server);
  registerInspectionTools(server);
  registerInteractionTools(server);
  registerTabDialogTools(server);
  registerNetworkTools(server);
  registerStateTools(server);
  registerTestingTools(server);
  registerAdvancedTools(server);
  registerTargetSecurityTools(server);
  registerOrchestrationTools(server);
  registerNativeChromeTools(server);
  registerBridgeTools(server);
  registerVisualTools(server);
}
