using System.Net;
using System.Net.Http.Json;
using System.Text.Json;
using Zagent.Core.Abstractions;
using Zagent.Core.Agents.Tunnel;
using Zagent.Core.Manager;
using Zagent.Core.Supervision;
using Zagent.Shared;
using Zagent.Shared.Contracts;
using Zagent.Shared.Manager;

namespace Zagent.Core.Agents.Qgis;

public sealed record QgisIntegrationOptions(string PythonExecutable, string UpstreamRoot,
    string BindHost = "127.0.0.1", int Port = Zagent.Core.Network.ZagentNetworkPolicy.QgisPort);

/// <summary>Core owns the upstream MCP process, never the external QGIS GUI.</summary>
public static class QgisIntegration
{
    public const string AgentId = "qgis.service";
    public const string ProcessId = "qgis.mcp";

    public static QgisIntegrationOptions? Resolve(ManagerCoreHostOptions options)
    {
        var python = options.QgisPython ?? Environment.GetEnvironmentVariable("ZAGENT_QGIS_PYTHON");
        var root = options.QgisRoot ?? Environment.GetEnvironmentVariable("ZAGENT_QGIS_ROOT");
        // Prefer this installation's bundled QGIS agent. The external QGIS
        // Desktop is not a supervised/owned process.
        if (string.IsNullOrWhiteSpace(python) && string.IsNullOrWhiteSpace(root))
        {
            var agent = Path.Combine(Path.GetFullPath(options.ZagentRoot), "agents", "qgis");
            var bundledPython = Path.Combine(agent, "runtime", "python", "python.exe");
            var bundledEngine = Path.Combine(agent, "engine");
            if (!File.Exists(bundledPython) ||
                !File.Exists(Path.Combine(bundledEngine, "src", "qgis_mcp", "server.py")) ||
                !File.Exists(Path.Combine(bundledEngine, "src", "zagent_qgis", "launch.py")))
                return null; // Optional: an incomplete bundle cannot block Core startup.
            return new(bundledPython, bundledEngine, "127.0.0.1", options.QgisPort);
        }
        if (string.IsNullOrWhiteSpace(python) || string.IsNullOrWhiteSpace(root))
            throw new ArgumentException("QGIS requires both ZAGENT_QGIS_PYTHON and ZAGENT_QGIS_ROOT.");
        return new(python, root, "127.0.0.1", options.QgisPort);
    }

    public static AgentProcessDefinition CreateProcess(QgisIntegrationOptions options)
    {
        if (!IPAddress.TryParse(options.BindHost, out var host) || !IPAddress.IsLoopback(host))
            throw new ArgumentException("QGIS MCP must bind a loopback IP.");
        if (options.Port is < 1 or > 65535) throw new ArgumentOutOfRangeException(nameof(options.Port));
        if (!File.Exists(options.PythonExecutable)) throw new FileNotFoundException("QGIS upstream Python missing.");
        var source = Path.Combine(Path.GetFullPath(options.UpstreamRoot), "src");
        if (!File.Exists(Path.Combine(source,"qgis_mcp","server.py")))
            throw new FileNotFoundException("QGIS upstream src/qgis_mcp/server.py missing.");
        if (!File.Exists(Path.Combine(source,"zagent_qgis","launch.py")))
            throw new FileNotFoundException("Zagent QGIS managed launcher missing.");
        return new AgentProcessDefinition(ProcessId, Path.GetFullPath(options.PythonExecutable),
            ["-m", "zagent_qgis.launch"], Path.GetFullPath(options.UpstreamRoot),
            EnvironmentVariables: new Dictionary<string,string> {
                ["PYTHONPATH"] = source, ["PYTHONUNBUFFERED"] = "1", ["PYTHONDONTWRITEBYTECODE"] = "1",
                ["QGIS_MCP_TRANSPORT"] = "streamable-http",
                ["ZAGENT_QGIS_BIND_HOST"] = options.BindHost, ["ZAGENT_QGIS_BIND_PORT"] = options.Port.ToString(),
                ["QGIS_MCP_HOST"] = "127.0.0.1", ["QGIS_MCP_PORT"] = "9876",
                ["QGIS_MCP_LOG_FILE"] = ""
            }, GracefulShutdownSeconds: 3, AutoRestart: true, MaxRestartAttempts: 3);
    }

    public static TunnelServiceDefinition CreateService(QgisIntegrationOptions options) =>
        new("zagent_qgis", "QGIS upstream", "qgis", $"http://{options.BindHost}:{options.Port}/mcp",
            TimeoutSeconds: 120, InternalAuth: false);

    public static void Register(QgisIntegrationOptions options, ICapabilityRegistry registry,
        IAgentSupervisor supervisor, ManagerAgentControllerRegistry controllers,
        bool productionApproved, AgentEnvironment environment)
    {
        var process = CreateProcess(options);
        var manifest = new AgentManifest(ZagentProductInfo.AgentProtocolVersion,
            new AgentIdentity(AgentId,"QGIS upstream MCP","1.0.0","nkarasiak/qgis-mcp"), environment,
            new AgentRuntimeDescriptor("python",">=3.12","zagent_qgis.launch"),
            new AgentTransportDescriptor("http-mcp",options.BindHost,options.Port,"/mcp",true),
            new AgentLifecycleDescriptor(GracefulShutdownSeconds:3),
            new AgentHealthDescriptor("mcp",CreateService(options).Url),
            [new CapabilityDescriptor("qgis.tools","Dynamic complete upstream MCP tool catalog.",
                CapabilityAccess.Action,CapabilityExecution.Background,CapabilityApproval.None,SupportsCancel:false)],
            Dependencies: [new AgentDependencyDescriptor("qgis.desktop",true,">=3.28",External:true)],
            Metadata: new Dictionary<string,string> { ["desktop_ownership"]="external", ["catalog"]="dynamic" });
        var registration=registry.Register(manifest,productionApproved);
        if (!registration.Success) throw new InvalidOperationException(string.Join("; ",registration.Errors));
        supervisor.Register(process);
        async Task<LifecycleOperationResult> Stop(CancellationToken ct)
        {
            var stopped=await supervisor.StopAsync(ProcessId,ct);
            registry.TrySetHealth(AgentId,stopped.Success?AgentHealthState.Offline:AgentHealthState.Failed);
            return new(stopped.Success,AgentId,"stop",stopped.Message);
        }
        async Task<LifecycleOperationResult> Start(CancellationToken ct)
        {
            var started=await supervisor.StartAsync(ProcessId,ct);
            if (!started.Success) return new(false,AgentId,"start",started.Message);
            var deadline=DateTime.UtcNow.AddSeconds(15);
            while(DateTime.UtcNow<deadline) {
                if(await ProbeAsync(options,ct)) {
                    registry.TrySetHealth(AgentId,AgentHealthState.Ready);
                    return new(true,AgentId,"start","QGIS MCP ready; GUI plugin connectivity is verified by qgis_ping.");
                }
                await Task.Delay(150,ct);
            }
            registry.TrySetHealth(AgentId,AgentHealthState.Failed);
            return new(false,AgentId,"start","QGIS MCP initialize timed out (GUI remains external).");
        }
        controllers.Register(new ManagerAgentController(AgentId,ProcessId,Start,Stop,async ct=>{
            var stopped=await Stop(ct); return stopped.Success?(await Start(ct)) with {Operation="restart"}:stopped;
        },async ct=>{
            var ready=await ProbeAsync(options,ct);
            registry.TrySetHealth(AgentId,ready?AgentHealthState.Ready:AgentHealthState.Offline);
            return new ManagerOperationResult(ready,"refresh",AgentId,ready?"QGIS MCP ready; GUI unverified.":"QGIS MCP offline.");
        }));
    }

    public static async Task<bool> ProbeAsync(QgisIntegrationOptions options,CancellationToken ct=default)
    {
        try {
            using var client=new HttpClient(new SocketsHttpHandler {UseProxy=false}) {Timeout=TimeSpan.FromSeconds(3)};
            client.DefaultRequestHeaders.Accept.ParseAdd("application/json, text/event-stream");
            using var response=await client.PostAsJsonAsync(CreateService(options).Url,new {
                jsonrpc="2.0",id="core-qgis-health",method="initialize",@params=new {
                    protocolVersion="2025-06-18",capabilities=new {},clientInfo=new {name="Zagent-Core",version="1.0"}
                }},ct);
            if(!response.IsSuccessStatusCode)return false;
            var text=await response.Content.ReadAsStringAsync(ct);
            if(response.Content.Headers.ContentType?.MediaType=="text/event-stream")
                text=text.Split('\n').Last(line=>line.StartsWith("data:",StringComparison.Ordinal))[5..].Trim();
            using var doc=JsonDocument.Parse(text);
            var ready=doc.RootElement.TryGetProperty("result",out var result) && result.TryGetProperty("serverInfo",out _);
            // This is a private probe session, not Router's long-lived session.
            if(response.Headers.TryGetValues("mcp-session-id",out var ids)) {
                using var close=new HttpRequestMessage(HttpMethod.Delete,CreateService(options).Url);
                close.Headers.Add("Mcp-Session-Id",ids.First());
                close.Headers.Add("MCP-Protocol-Version","2025-06-18");
                using var ignored=await client.SendAsync(close,ct);
            }
            return ready;
        } catch(Exception ex) when(ex is HttpRequestException or TaskCanceledException or JsonException or InvalidOperationException) {
            ct.ThrowIfCancellationRequested();return false;
        }
    }
}
