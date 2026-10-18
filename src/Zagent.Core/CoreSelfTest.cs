using Zagent.Core.Registry;
using Zagent.Shared.Contracts;

namespace Zagent.Core;

public static class CoreSelfTest
{
    public static int Run(TextWriter output)
    {
        ArgumentNullException.ThrowIfNull(output);

        var registry = new CapabilityRegistry();
        var manifest = SampleManifests.CreateDevelopmentEchoAgent();

        var first = registry.Register(manifest);
        if (!first.Success)
        {
            output.WriteLine(
                $"SELF_TEST_FAIL register: {string.Join("; ", first.Errors)}");
            return 10;
        }

        if (!registry.TrySetHealth(manifest.Agent.Id, AgentHealthState.Ready))
        {
            output.WriteLine("SELF_TEST_FAIL health update.");
            return 11;
        }

        if (!registry.TryGet(manifest.Agent.Id, out var registered) ||
            registered is null ||
            registered.Health != AgentHealthState.Ready)
        {
            output.WriteLine("SELF_TEST_FAIL registry lookup.");
            return 12;
        }

        var duplicate = registry.Register(manifest);
        if (duplicate.Success)
        {
            output.WriteLine("SELF_TEST_FAIL duplicate registration was accepted.");
            return 13;
        }

        output.WriteLine(
            $"SELF_TEST_PASS agent={manifest.Agent.Id} " +
            $"capabilities={manifest.Capabilities.Count} " +
            $"registry_count={registry.Snapshot().Count}");
        return 0;
    }
}
