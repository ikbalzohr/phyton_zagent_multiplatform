import test from "node:test";
import assert from "node:assert/strict";
import { registerAllTools } from "../src/tools/index.js";

test("all 151 Zagent Web tools register uniquely with valid metadata", () => {
  const entries = new Map();
  const server = {
    registerTool(name, config, callback) {
      assert.match(name, /^web_[a-z0-9_]+$/);
      assert.equal(entries.has(name), false, "duplicate tool: " + name);
      assert.equal(typeof callback, "function", "callback missing: " + name);
      assert.equal(typeof config, "object", "config missing: " + name);
      assert.equal(typeof config.description, "string", "description missing: " + name);
      assert.ok(config.description.trim().length > 5, "description too short: " + name);
      entries.set(name, { config, callback });
    }
  };

  registerAllTools(server);
  assert.equal(entries.size, 151);

  const representatives = [
    "web_ping",
    "web_open",
    "web_get_text",
    "web_click",
    "web_tabs",
    "web_network_requests",
    "web_cookies_get",
    "web_assert_text",
    "web_evaluate_js",
    "web_target_test",
    "web_session_open",
    "web_native_chrome_attach",
    "web_chrome_profiles",
    "web_chrome_launch_profile",
    "web_chrome_launch_status",
    "web_bridge_pair",
    "web_bridge_pair_status",
    "web_bridge_profile_binding",
    "web_bridge_authorize_request",
    "web_bridge_reconnect",
    "web_bridge_status"
  ];
  for (const name of representatives) assert.ok(entries.has(name), "missing category representative: " + name);

  const browserStartSchema = entries.get("web_browser_start").config.inputSchema;
  const sessionOpenSchema = entries.get("web_session_open").config.inputSchema;

  assert.equal(
    browserStartSchema.safeParse({ browser: "chrome" }).success,
    true,
    "web_browser_start must accept Google Chrome"
  );
  assert.equal(
    sessionOpenSchema.safeParse({
      sessionId: "chrome-only",
      browser: "chrome",
    }).success,
    true,
    "web_session_open must accept Google Chrome"
  );

  for (const browser of ["chromium", "firefox", "webkit", "unsupported"]) {
    assert.equal(
      browserStartSchema.safeParse({ browser }).success,
      false,
      "web_browser_start must reject non-Chrome browser: " + browser
    );
    assert.equal(
      sessionOpenSchema.safeParse({
        sessionId: "chrome-only",
        browser,
      }).success,
      false,
      "web_session_open must reject non-Chrome browser: " + browser
    );
  }
});
