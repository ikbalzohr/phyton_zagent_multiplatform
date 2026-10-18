using System.Text.RegularExpressions;
using Zagent.Shared;
using Zagent.Shared.Contracts;

namespace Zagent.Core.Registry;

public interface IAgentManifestValidator
{
    ManifestValidationResult Validate(AgentManifest manifest);
}

public sealed partial class AgentManifestValidator : IAgentManifestValidator
{
    public ManifestValidationResult Validate(AgentManifest manifest)
    {
        ArgumentNullException.ThrowIfNull(manifest);

        var errors = new List<string>();

        if (!string.Equals(
                manifest.ProtocolVersion,
                ZagentProductInfo.AgentProtocolVersion,
                StringComparison.Ordinal))
        {
            errors.Add(
                $"Unsupported protocol version '{manifest.ProtocolVersion}'. " +
                $"Expected '{ZagentProductInfo.AgentProtocolVersion}'.");
        }

        if (!AgentIdRegex().IsMatch(manifest.Agent.Id))
        {
            errors.Add($"Invalid agent id '{manifest.Agent.Id}'.");
        }

        if (string.IsNullOrWhiteSpace(manifest.Agent.Name))
        {
            errors.Add("Agent name is required.");
        }

        if (string.IsNullOrWhiteSpace(manifest.Agent.Version))
        {
            errors.Add("Agent version is required.");
        }

        if (string.IsNullOrWhiteSpace(manifest.Runtime.Language))
        {
            errors.Add("Runtime language is required.");
        }

        if (string.IsNullOrWhiteSpace(manifest.Runtime.Entrypoint))
        {
            errors.Add("Runtime entrypoint is required.");
        }

        if (!manifest.Transport.LocalOnly)
        {
            errors.Add("Agent Protocol v1 requires local-only transport.");
        }

        if (manifest.Transport.Port is < 1 or > 65535)
        {
            errors.Add($"Invalid transport port '{manifest.Transport.Port}'.");
        }

        if (manifest.Health.IntervalSeconds < 1)
        {
            errors.Add("Health interval must be at least 1 second.");
        }

        if (manifest.Health.TimeoutSeconds < 1)
        {
            errors.Add("Health timeout must be at least 1 second.");
        }

        if (manifest.Lifecycle.GracefulShutdownSeconds is < 0 or > 300)
        {
            errors.Add("Graceful shutdown must be between 0 and 300 seconds.");
        }

        if (manifest.Capabilities.Count == 0)
        {
            errors.Add("At least one capability is required.");
        }

        var capabilityNames = new HashSet<string>(StringComparer.Ordinal);
        foreach (var capability in manifest.Capabilities)
        {
            if (!CapabilityNameRegex().IsMatch(capability.Name))
            {
                errors.Add($"Invalid capability name '{capability.Name}'.");
            }

            if (!capabilityNames.Add(capability.Name))
            {
                errors.Add($"Duplicate capability '{capability.Name}'.");
            }
        }

        return errors.Count == 0
            ? ManifestValidationResult.Success
            : new ManifestValidationResult(false, errors);
    }

    [GeneratedRegex("^[a-z][a-z0-9._-]{2,63}$", RegexOptions.CultureInvariant)]
    private static partial Regex AgentIdRegex();

    [GeneratedRegex("^[a-z][a-z0-9_-]*(\\.[a-z0-9_-]+)+$", RegexOptions.CultureInvariant)]
    private static partial Regex CapabilityNameRegex();
}
