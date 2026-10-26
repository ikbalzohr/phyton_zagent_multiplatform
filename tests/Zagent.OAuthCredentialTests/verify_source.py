"""Source-only contract checks. Does not import/build/execute product code."""
from pathlib import Path
import xml.etree.ElementTree as ET

root = Path(__file__).resolve().parents[2]
store = (root / "src/Zagent.Core/Manager/OAuthIntrospectionCredentialStore.cs").read_text(encoding='utf-8')
factory = (root / "src/Zagent.Core/Agents/Tunnel/TunnelProcessFactory.cs").read_text(encoding='utf-8')
supervisor = (root / "src/Zagent.Core/Supervision/NativeAgentSupervisor.cs").read_text(encoding='utf-8')
host = (root / "src/Zagent.Core/Manager/ManagerCoreHost.cs").read_text(encoding='utf-8')
writer = (root / "src/Zagent.Core/Agents/Tunnel/TunnelConfigurationWriter.cs").read_text(encoding='utf-8')
for token in ('RSAEncryptionPadding.OaepSHA256', 'cert.GetRSAPrivateKey()', 'CngExportPolicies.None',
              'StoreLocation.CurrentUser', 'FileMode.CreateNew', 'FileShare.None', 'expires - now > 86400',
              'SHA256.HashData(cert.RawData)', 'CryptographicOperations.ZeroMemory(clear)',
              '"version", "scope", "protected_payload"', '"issuer", "client_id", "secret"'):
    assert token in store, token
assert 'Text(resource, "introspection_endpoint") != Issuer + "/protocol/openid-connect/token/introspect"' in store, 'Missing trusted introspection endpoint binding'
assert 'OAuthCredentialDataRoot: data' in host
assert 'LoadOptional(' in factory.split('public static AgentProcessDefinition CreateTransport')[0]
assert 'LoadOptional(' not in factory.split('public static AgentProcessDefinition CreateTransport')[1]
assert 'startInfo.Environment.Remove(Zagent.Core.Manager.OAuthIntrospectionCredentialStore.EnvironmentName)' in supervisor
assert 'definition.AgentId != Zagent.Core.Agents.Tunnel.TunnelProcessFactory.RouterProcessId' in supervisor
assert 'merged[entry.Key] = entry.Value?.DeepClone()' in writer
assert 'resource_server =' not in writer
assert 'SetEnvironmentVariable' not in store + factory
files_helpers = (root / 'src/Zagent.Core/Manager/FilesManagerReadModel.cs').read_text(encoding='utf-8')
assert files_helpers.count('startInfo.Environment.Remove(OAuthIntrospectionCredentialStore.EnvironmentName);') == 2, 'Both Files helper paths must strip OAuth before launch'
program = (root / 'src/Zagent.Core/Program.cs').read_text(encoding='utf-8')
assert 'Environment.SetEnvironmentVariable(OAuthIntrospectionCredentialStore.EnvironmentName, null);' in program, 'Core must discard process-local ambient OAuth before dispatch'
assert 'ExportParameters' not in store and 'ExportPkcs8PrivateKey' not in store
for path in (root / 'tests/Zagent.OAuthCredentialTests/Zagent.OAuthCredentialTests.csproj',
             root / 'packaging/scripts/OAuthCredentialImport/OAuthCredentialImport.csproj'):
    ET.parse(path)
print('PASS: source-only OAuth contract/isolation assertions and two project XML parses.')
print('NOT_RUN: Windows compilation, behavioral tests, certificate import, RSA/DPAPI/ACL runtime.')
