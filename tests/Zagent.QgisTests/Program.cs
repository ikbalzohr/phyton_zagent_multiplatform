using Zagent.Core.Agents.Qgis;
using Zagent.Core.Manager;
var root = Path.Combine(Path.GetTempPath(), "zagent-qgis-test-"+Guid.NewGuid().ToString("N"));
Directory.CreateDirectory(Path.Combine(root,"src","qgis_mcp"));
Directory.CreateDirectory(Path.Combine(root,"src","zagent_qgis"));
var python=Path.Combine(root,"python.exe");File.WriteAllText(python,"");
File.WriteAllText(Path.Combine(root,"src","qgis_mcp","server.py"),"");
File.WriteAllText(Path.Combine(root,"src","zagent_qgis","launch.py"),"");
try {
 Check(new QgisIntegrationOptions(python,root).Port==19150,"isolated QGIS default port");
 Check(new ManagerCoreHostOptions(root,root,root).QgisPort==19150,"Core QGIS port default");
 var options=new QgisIntegrationOptions(python,root,"127.0.0.1",18850);
 var process=QgisIntegration.CreateProcess(options);
 Check(process.AgentId=="qgis.mcp","process id");
 Check(process.Arguments.SequenceEqual(new[]{"-m","zagent_qgis.launch"}),"upstream module");
 Check(process.EnvironmentVariables!["QGIS_MCP_TRANSPORT"]=="streamable-http","http transport");
 Check(process.EnvironmentVariables["PYTHONDONTWRITEBYTECODE"]=="1","no runtime bytecode artifacts");
 Check(process.EnvironmentVariables["ZAGENT_QGIS_BIND_HOST"]=="127.0.0.1","loopback bind");
 Check(process.EnvironmentVariables["ZAGENT_QGIS_BIND_PORT"]=="18850","port");
 Check(!process.EnvironmentVariables.Keys.Any(k=>k.Contains("INTERNAL_TOKEN")),"no Core secret");
 var service=QgisIntegration.CreateService(options);
 Check(service.Namespace=="qgis" && !service.InternalAuth,"third-party service");
 Check(QgisIntegration.Resolve(new ManagerCoreHostOptions(root,root,root)) is null,"unconfigured stays absent");
 var embeddedRoot = Path.Combine(root, "agents", "qgis");
 var embeddedEngine = Path.Combine(embeddedRoot, "engine", "src", "qgis_mcp");
 var embeddedRuntime = Path.Combine(embeddedRoot, "runtime", "python");
 Directory.CreateDirectory(embeddedEngine);
 Directory.CreateDirectory(Path.Combine(embeddedRoot, "engine", "src", "zagent_qgis"));
 Directory.CreateDirectory(embeddedRuntime);
 File.WriteAllText(Path.Combine(embeddedEngine, "server.py"), "");
 File.WriteAllText(Path.Combine(embeddedRoot, "engine", "src", "zagent_qgis", "launch.py"), "");
 var embeddedPython = Path.Combine(embeddedRuntime, "python.exe");
 File.WriteAllText(embeddedPython, "");
 var resolved=QgisIntegration.Resolve(new ManagerCoreHostOptions(root,root,root));
 Check(resolved is not null && resolved.PythonExecutable==embeddedPython &&
     resolved.UpstreamRoot==Path.Combine(embeddedRoot,"engine"),
     "bundled QGIS auto-enrolled without external path");
 Check(QgisIntegration.CreateProcess(resolved!).Arguments.SequenceEqual(new[]{"-m","zagent_qgis.launch"}),
     "bundled executable uses native module entrypoint");
 File.Delete(embeddedPython);
 Check(QgisIntegration.Resolve(new ManagerCoreHostOptions(root,root,root)) is null,
     "missing bundled runtime cannot block Core");
 try {QgisIntegration.CreateProcess(options with {BindHost="0.0.0.0"});throw new Exception("public bind accepted");}
 catch(ArgumentException){}
 Console.WriteLine("QGIS_TEST_PASS process/service/optional/loopback contracts");return 0;
} finally {Directory.Delete(root,true);}
static void Check(bool ok,string message){if(!ok)throw new Exception(message);}
