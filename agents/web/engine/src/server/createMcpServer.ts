import { McpServer } from "@modelcontextprotocol/server";
import { installExecutionGate } from './executionContext.js';
import { registerAllTools } from "../tools/index.js";
import { installBridgeGate } from '../bridge/gate.js';

export function buildMcpServer(): McpServer {
  const server = new McpServer({
    name: "Zagent Web",
    version: "1.0.0",
  });

  installExecutionGate(server);
  installBridgeGate(server);
  registerAllTools(server);
  return server;
}
