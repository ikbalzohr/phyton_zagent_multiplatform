using System.Text.Json;
using Zagent.Core.Diagnostics;
using Zagent.Core.Dashboard;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Routing;
using System.Security.Claims;
if (args.Contains("--diagnostic-test-child")) return;
if (args.Length == 2 && args[0] == "--read-diagnostic-fixture") {
 Console.WriteLine(JsonSerializer.Serialize(new DiagnosticEventStore(args[1]).Read(500), new JsonSerializerOptions(JsonSerializerDefaults.Web)));
 return;
}
var root = Path.Combine(Path.GetTempPath(), "zagent-diagnostics-" + Guid.NewGuid().ToString("N"));
int passed = 0;
void Check(bool value, string name) { if (!value) throw new Exception(name); passed++; Console.WriteLine("PASS " + name); }
try {
 var store = new DiagnosticEventStore(root);
 var id = store.Record("dashboard.request", "DASHBOARD_REQUEST_FAILED", "error");
 var report = store.Read();
 Check(report.Events.Count == 1 && report.Events[0].RequestId == id && id.Length == 32, "persistent structured event and correlation");
 var directory = Path.Combine(root, "logs", "diagnostics");
 string Line(string code = "AUTH_INVALID_TOKEN", string stage = "auth", string message = "PRIVATE_TOKEN_path_secret", string? request = null) => JsonSerializer.Serialize(new { version = 1, timestampUtc = "2026-10-30T00:00:00Z", requestId = request ?? id, component = "router", stage, code, severity = "error", message }) + "\n";
 File.WriteAllText(Path.Combine(directory,"router.jsonl"), Line());
 report = store.Read();
 Check(report.Events.Count == 2 && !JsonSerializer.Serialize(report).Contains("PRIVATE_TOKEN"), "tampered messages reconstructed from static code");
 File.AppendAllText(Path.Combine(directory,"router.jsonl"), Line("SECRET_CODE") + Line(stage:"SECRET_STAGE") + Line(request:"BAD_ID") + "{broken\n{truncated");
 report = store.Read();
 Check(report.Sources.Single(s => s.Component == "router").Ignored == 5, "invalid schema code stage id corrupt and truncated counted");
 File.AppendAllText(Path.Combine(directory,"router.jsonl"), "\n" + Line().Replace("2026-10-30T00:00:00Z", "2026-10-30 00:00:00Z"));
 Check(store.Read().Sources.Single(s=>s.Component == "router").Ignored == 6, "non ISO timestamp rejected");
 File.AppendAllText(Path.Combine(directory,"router.jsonl"), Line().Replace("\"version\":1", "\"version\":1,\"version\":1") + Line().Replace("\"version\":1", "\"extra\":\"SECRET\",\"version\":1"));
 Check(store.Read().Sources.Single(s=>s.Component == "router").Ignored == 8, "duplicate and unknown fields rejected");
 Check(store.Read(component:"core", severity:"error", requestId:id).Events.Count == 1, "exact component severity request correlation filters");
 bool invalid = false; try { store.Read(501); } catch (ArgumentException) { invalid = true; }
 Check(invalid && !DiagnosticEventStore.ValidFilters("../../", null, null), "invalid filters and bounds rejected");
 File.WriteAllText(Path.Combine(directory,"files.jsonl"), new string('x', DiagnosticEventStore.MaxFileBytes + 1));
 Check(store.Read().Sources.Single(s => s.Component == "files").Status == "unavailable", "oversize files rejected bounded");
 File.WriteAllText(Path.Combine(directory,"files.jsonl"), new string('x', DiagnosticEventStore.MaxRecordBytes + 1) + "\n");
 Check(store.Read().Sources.Single(s => s.Component == "files").Truncated == 1, "oversize records rejected bounded");
 File.Delete(Path.Combine(directory,"files.jsonl"));
 File.CreateSymbolicLink(Path.Combine(directory,"files.jsonl"), Path.Combine(directory,"core.jsonl"));
 Check(store.Read().Sources.Single(s => s.Component == "files").Status == "unavailable", "symlink log rejected");
 File.Delete(Path.Combine(directory,"files.jsonl"));
 File.WriteAllText(Path.Combine(directory,"core.jsonl"), new string('x', DiagnosticEventStore.RotationBytes));
 store.Record("dashboard.request", "DASHBOARD_REQUEST_FAILED", "error");
 Check(File.Exists(Path.Combine(directory,"core.jsonl.1")), "writer rotates at one MiB");
 var empty = new DiagnosticEventStore(Path.Combine(root,"empty")).Read();
 Check(empty.Status == "no_events" && empty.Sources.All(s=>s.Status == "missing"), "missing diagnostics never healthy");
 File.WriteAllText(Path.Combine(root,"blocked"), "not directory");
 new DiagnosticEventStore(Path.Combine(root,"blocked")).Record("dashboard.request", "DASHBOARD_REQUEST_FAILED", "error");
 Check(true, "writer IO failure does not escape");
 await using (var supervisor = new Zagent.Core.Supervision.NativeAgentSupervisor(false, diagnostics: store)) {
   supervisor.Register(new Zagent.Core.Supervision.AgentProcessDefinition("fixture", Path.Combine(root,"missing-executable"), []));
   var runtimeSnapshot = DashboardDiagnostics.CaptureRuntime(new Zagent.Core.Manager.ManagerCoreHostOptions(root, root, root, BindHost:"127.0.0.3", TunnelPort:20101, TunnelHealthPort:20102, FilesPort:20103), supervisor, false);
   Check(runtimeSnapshot.BindHost == "127.0.0.3" && runtimeSnapshot.RouterPort == 20101 && runtimeSnapshot.FilesPort == 20103 && !JsonSerializer.Serialize(runtimeSnapshot).Contains("missing-executable"), "runtime bind and ports use options without raw supervisor errors");
   var start = await supervisor.StartAsync("fixture");
   Check(!start.Success && store.Read().Events.Any(e=>e.Code == "CORE_AGENT_START_FAILED"), "real supervisor failed start captured without exception text");
   var host = Environment.GetEnvironmentVariable("DOTNET_HOST_PATH") ?? (string.Equals(Path.GetFileNameWithoutExtension(Environment.ProcessPath), "dotnet", StringComparison.OrdinalIgnoreCase) ? Environment.ProcessPath! : "dotnet");
   supervisor.Register(new Zagent.Core.Supervision.AgentProcessDefinition("exit-fixture", host, [System.Reflection.Assembly.GetExecutingAssembly().Location, "--diagnostic-test-child"], WorkingDirectory:sourceDirectory(), GracefulShutdownSeconds:0));
   var child = await supervisor.StartAsync("exit-fixture");
   for (int retry = 0; retry < 100 && !store.Read().Events.Any(e=>e.Code == "CORE_AGENT_EXITED"); retry++) await Task.Delay(50);
   Check(child.Success && store.Read().Events.Any(e=>e.Code == "CORE_AGENT_EXITED"), "real isolated child unexpected exit captured");
 }
 string sourceDirectory() => AppContext.BaseDirectory;
 try { await Zagent.Core.Manager.ManagerCoreHost.CreateAsync(new Zagent.Core.Manager.ManagerCoreHostOptions(Path.Combine(root,"missing-root"),root,root), false); throw new Exception("missing root accepted"); }
 catch (DirectoryNotFoundException) { }
 Check(store.Read().Events.Any(e=>e.Code == "CORE_START_FAILED"), "real host startup prerequisite failure captured without Windows guard bypass");
 var errorContext = new DefaultHttpContext();
 errorContext.TraceIdentifier = "CALLER_SUPPLIED_SECRET";
 errorContext.Response.Body = new MemoryStream();
 errorContext.Response.Headers.ContentSecurityPolicy = "default-src 'self'";
 await DashboardDiagnostics.HandleRequestAsync(errorContext, _ => throw new Exception("RAW_EXCEPTION_SECRET"), store);
 Check(errorContext.Response.StatusCode == 503 && DiagnosticEventStore.ValidRequestId(errorContext.TraceIdentifier) && store.Read(requestId:errorContext.TraceIdentifier).Events.Count == 1, "dashboard error response has generated exact event correlation");
 errorContext.Response.Body.Position = 0;
 var errorBody = await new StreamReader(errorContext.Response.Body).ReadToEndAsync();
 Check(!errorBody.Contains("SECRET") && errorBody.Contains(errorContext.TraceIdentifier), "error response does not disclose exception or incoming trace");
 Check(errorContext.Response.Headers.ContentSecurityPolicy == "default-src 'self'", "error response retains security headers");
 var builder = WebApplication.CreateBuilder();
 builder.Services.AddAuthorization(o => o.AddPolicy("Administrator", p => p.RequireAuthenticatedUser().RequireRole("Administrator")));
 await using var app = builder.Build();
 app.MapDiagnostics(store, () => new DiagnosticRuntimeSnapshot("running", "127.0.0.3", 18810, 18811, 18820, []));
 var endpoints = ((IEndpointRouteBuilder)app).DataSources.SelectMany(s=>s.Endpoints).ToArray();
 Check(endpoints.Length == 2 && endpoints.All(e=>e.Metadata.GetMetadata<IAuthorizeData>()?.Policy == "Administrator"), "both report and export require Administrator");
 var auth = app.Services.GetRequiredService<IAuthorizationService>();
 Check(!(await auth.AuthorizeAsync(new ClaimsPrincipal(new ClaimsIdentity()), null, "Administrator")).Succeeded, "anonymous diagnostics access denied");
 Check((await auth.AuthorizeAsync(new ClaimsPrincipal(new ClaimsIdentity(new[]{new Claim(ClaimTypes.Role,"Administrator")},"fixture")), null, "Administrator")).Succeeded, "explicit owner-role fixture authorized");
 async Task<(DefaultHttpContext Context, string Body)> Invoke(string route, string query) {
   var endpoint = (RouteEndpoint)endpoints.Single(e => ((RouteEndpoint)e).RoutePattern.RawText == route);
   var ctx = new DefaultHttpContext { RequestServices = app.Services, TraceIdentifier = Guid.NewGuid().ToString("N") };
   ctx.Request.QueryString = new QueryString(query); ctx.Response.Body = new MemoryStream();
   await endpoint.RequestDelegate!(ctx); ctx.Response.Body.Position = 0;
   return (ctx, await new StreamReader(ctx.Response.Body).ReadToEndAsync());
 }
 var api = await Invoke("/api/management/v1/diagnostics", "?component=core&limit=1");
 using (var json = JsonDocument.Parse(api.Body)) Check(api.Context.Response.StatusCode == 200 && json.RootElement.GetProperty("events").GetArrayLength() == 1 && json.RootElement.GetProperty("runtime").GetProperty("bindHost").GetString() == "127.0.0.3", "real report endpoint bounded safe runtime response");
 var export = await Invoke("/api/management/v1/diagnostics/export", "?limit=500");
 Check(export.Context.Response.Headers.ContentDisposition.ToString().Contains("zagent-diagnostics.json") && export.Context.Response.ContentType == "application/json" && !export.Body.Contains("PRIVATE_TOKEN") && !export.Body.Contains("missing-executable"), "real export attachment contains safe projection only");
 var invalidQuery = await Invoke("/api/management/v1/diagnostics", "?path=private");
 var duplicateQuery = await Invoke("/api/management/v1/diagnostics", "?component=core&component=router");
 Check(invalidQuery.Context.Response.StatusCode == 400 && duplicateQuery.Context.Response.StatusCode == 400, "real endpoints reject paths and duplicate query keys");
 foreach (var stage in new[] { "auth.token", "router.configuration", "mcp.auth_context", "mcp.handler", "mcp.initialize", "mcp.tools_list", "mcp.tools_call", "job.scheduler", "upstream.dispatch" }) {
   File.WriteAllText(Path.Combine(directory,"router.jsonl"), Line(stage:stage));
   Check(store.Read(component:"router").Events.Single().Stage == stage, "Python Router stage contract " + stage);
 }
 File.WriteAllText(Path.Combine(directory,"router.jsonl"), Line("ROUTER_PROTOCOL_ERROR", "mcp.protocol"));
 Check(store.Read(component:"router").Events.Single().Message == "Request arguments or protocol were rejected. Check the published input schema.", "protocol hint covers client rejection without claiming upstream failure");
 File.WriteAllText(Path.Combine(directory,"files.jsonl"), Line("FILES_OPERATION_FAILED", "files.tool_dispatch").Replace("\"component\":\"router\"", "\"component\":\"files\""));
 Check(store.Read(component:"files").Events.Single().Stage == "files.tool_dispatch", "Python Files stage and component contract");
 File.Delete(Path.Combine(directory,"files.jsonl"));
 typeof(Zagent.Core.Manager.InternalManagementChannel).GetMethod("Configure", System.Reflection.BindingFlags.NonPublic | System.Reflection.BindingFlags.Static)!.Invoke(null,
     new object[] { Guid.NewGuid().ToString("N"), Guid.NewGuid().ToString("N"), "fixture-workspace", "fixture-device", "fixture-installation", root });
 var routerOptions = new Zagent.Core.Agents.Tunnel.TunnelIntegrationOptions(Environment.ProcessPath!, root, root, root, Path.Combine(root,"chat.jsonl"), "127.0.0.3", 18810);
 var routerRootProperty = routerOptions.GetType().GetProperty("CoreDataRoot");
 Check(routerRootProperty is not null, "Router has explicit Core diagnostic DataRoot option");
 routerRootProperty!.SetValue(routerOptions, root);
 var routerDefinition = Zagent.Core.Agents.Tunnel.TunnelProcessFactory.CreateRouter(routerOptions);
 Check(routerDefinition.EnvironmentVariables!["ZAGENT_CORE_DATA_ROOT"] == Path.GetFullPath(root), "Core propagates explicit diagnostic DataRoot to Router child");
 routerRootProperty.SetValue(routerOptions, null);
 Check(Zagent.Core.Agents.Tunnel.TunnelProcessFactory.CreateRouter(routerOptions).EnvironmentVariables!["ZAGENT_CORE_DATA_ROOT"] == "", "unenrolled Router clears ambient diagnostic DataRoot");
 var sourceRoot = Path.GetFullPath(Path.Combine(AppContext.BaseDirectory, "../../../../../"));
 var markup = File.ReadAllText(Path.Combine(sourceRoot,"src/Zagent.Core/Pages/Index.cshtml"));
 var script = File.ReadAllText(Path.Combine(sourceRoot,"src/Zagent.Core/wwwroot/dashboard.js"));
 Check(markup.Contains("href=\"#diagnostics\"") && markup.Contains("id=\"diagnostics-form\"") && script.Contains("current === 'diagnostics'") && !script.Contains("innerHTML"), "diagnostics navigation search export and text-only DOM present");
 Console.WriteLine($"PASS {passed} diagnostic checks");
} finally { if (Directory.Exists(root)) Directory.Delete(root, true); }
