using Zagent.Core.Agents.Qgis;
using Zagent.Core.Manager;
var root = Path.Combine(Path.GetTempPath(), "zagent-qgis-test-"+Guid.NewGuid().ToString("N"));
Directory.CreateDirectory(Path.Combine(root,"src","qgis_mcp"));
var python=Path.Combine(root,"python.exe");File.WriteAllText(python,"");
File.WriteAllText(Path.Combine(root,"src","qgis_mcp","server.py"),"");
try {
 Check(new QgisIntegrationOptions(python,root).Port==19150,"isolated QGIS default port");
 Check(new ManagerCoreHostOptions(root,root,root).QgisPort==19150,"Core QGIS port default");
 var options=new QgisIntegrationOptions(python,root,"127.0.0.1",18850);
 var process=QgisIntegration.CreateProcess(options);
 Check(process.AgentId=="qgis.mcp","process id");
 Check(process.Arguments.SequenceEqual(new[]{"-m","qgis_mcp.server"}),"upstream module");
 Check(process.EnvironmentVariables!["QGIS_MCP_TRANSPORT"]=="streamable-http","http transport");
 Check(process.EnvironmentVariables["FASTMCP_HOST"]=="127.0.0.1","loopback bind");
 Check(process.EnvironmentVariables["FASTMCP_PORT"]=="18850","port");
 Check(!process.EnvironmentVariables.Keys.Any(k=>k.Contains("INTERNAL_TOKEN")),"no Core secret");
 var service=QgisIntegration.CreateService(options);
 Check(service.Namespace=="qgis" && !service.InternalAuth,"third-party service");
 Check(QgisIntegration.Resolve(new ManagerCoreHostOptions(root,root,root)) is null,"unconfigured stays absent");
 try {QgisIntegration.CreateProcess(options with {BindHost="0.0.0.0"});throw new Exception("public bind accepted");}
 catch(ArgumentException){}
 Console.WriteLine("QGIS_TEST_PASS process/service/optional/loopback contracts");return 0;
} finally {Directory.Delete(root,true);}
static void Check(bool ok,string message){if(!ok)throw new Exception(message);}
