using Zagent.Core.Configuration;

namespace Zagent.Core.Agents.Files;

public sealed class FilesConfigurationWriter
{
    private readonly AtomicJsonFileStore _store;

    public FilesConfigurationWriter(
        AtomicJsonFileStore? store = null)
    {
        _store = store ?? new AtomicJsonFileStore();
    }

    public async Task WriteAsync(
        FilesIntegrationOptions options,
        CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(options);
        Validate(options);

        Directory.CreateDirectory(options.DataRoot);
        Directory.CreateDirectory(options.ConfigRoot);
        Directory.CreateDirectory(options.RuntimeRoot);
        Directory.CreateDirectory(options.LogRoot);
        Directory.CreateDirectory(options.BackupRoot);
        Directory.CreateDirectory(options.UpdateStateRoot);
        Directory.CreateDirectory(options.DefaultProfileRoot);

        var settings = new
        {
            version = "3.3.0-v3",
            host = options.BindHost,
            port = options.Port,
            max_read_bytes = 10 * 1024 * 1024,
            max_write_bytes = 50 * 1024 * 1024,
            max_stage_file_bytes = 20 * 1024 * 1024,
            max_stage_total_bytes = 100 * 1024 * 1024,
            protect_secret_names = true,
            secret_names = new[]
            {
                ".env",
                ".env.development",
                ".env.local",
                ".env.production",
                "credentials.json",
                "id_ed25519",
                "id_rsa",
                "secrets.json"
            },
            backup_on_overwrite = true
        };

        var profiles = await BuildProfilesAsync(
            options,
            cancellationToken);

        var commandPolicy = new
        {
            schema_version = 1,
            command_layer_version = "3.1.3",
            allowed_executables = new[]
            {
                "node",
                "node.exe",
                "npm",
                "npm.cmd",
                "npx",
                "npx.cmd",
                "git",
                "git.exe",
                "python",
                "python.exe",
                "py",
                "py.exe",
                "powershell",
                "powershell.exe",
                "pwsh",
                "pwsh.exe",
                "cmd",
                "cmd.exe"
            },
            deny_powershell_patterns = new[]
            {
                @"(?i)\bset-executionpolicy\b",
                @"(?i)\badd-mppreference\b",
                @"(?i)\bset-mppreference\b",
                @"(?i)\bnew-localuser\b",
                @"(?i)\bremove-localuser\b",
                @"(?i)\bnet\s+user\b",
                @"(?i)\breg(\.exe)?\s+(add|delete)\b",
                @"(?i)\bsc(\.exe)?\s+(create|delete|config)\b",
                @"(?i)\bschtasks(\.exe)?\s+/(create|delete|change)\b",
                @"(?i)\bformat(\.com)?\b",
                @"(?i)\bdiskpart\b",
                @"(?i)\bbcdedit\b"
            },
            max_timeout_seconds = 1800,
            max_output_chars = 200000,
            allow_unmanaged_process_stop = true
        };

        await _store.SaveAsync(
            Path.Combine(options.ConfigRoot, "settings.json"),
            settings,
            cancellationToken);

        await _store.SaveAsync(
            Path.Combine(options.ConfigRoot, "profiles.json"),
            profiles,
            cancellationToken);

        await _store.SaveAsync(
            Path.Combine(options.ConfigRoot, "command_policy.json"),
            commandPolicy,
            cancellationToken);
    }

    private async Task<FilesProfilesDocument> BuildProfilesAsync(
        FilesIntegrationOptions options,
        CancellationToken cancellationToken)
    {
        var profilesPath = Path.Combine(
            options.ConfigRoot,
            "profiles.json");

        FilesProfilesDocument existing;
        if (_store.Exists(profilesPath))
        {
            existing = await _store.LoadAsync<FilesProfilesDocument>(
                profilesPath,
                cancellationToken);

            if (existing.Profiles is null)
            {
                throw new InvalidDataException(
                    "Existing Files profiles configuration is missing the profiles array.");
            }
        }
        else
        {
            existing = new FilesProfilesDocument();
        }

        var merged = new List<FilesProfileDocumentEntry>();
        var seen = new HashSet<string>(
            StringComparer.OrdinalIgnoreCase);

        foreach (var profile in existing.Profiles)
        {
            if (!profile.AuthorizedByUser ||
                string.IsNullOrWhiteSpace(profile.Name) ||
                !seen.Add(profile.Name))
            {
                continue;
            }

            merged.Add(profile);
        }

        var defaultName = options.DefaultProfileName;
        var existingDefaultIndex = merged.FindIndex(
            item => string.Equals(
                item.Name,
                defaultName,
                StringComparison.OrdinalIgnoreCase));
        var existingDefault =
            existingDefaultIndex >= 0
                ? merged[existingDefaultIndex]
                : null;

        var installerDefault = new FilesProfileDocumentEntry
        {
            Name = defaultName,
            Root = Path.GetFullPath(options.DefaultProfileRoot),
            Mode = options.DefaultProfileMode,
            Description =
                existingDefault?.Description ??
                "Zagent default Files profile",
            Enabled = true,
            AuthorizedByUser = true,
            AuthorizedAt =
                existingDefault?.AuthorizedAt ??
                DateTimeOffset.UtcNow,
            AuthorizationSource =
                existingDefault?.AuthorizationSource ??
                "zagent_install"
        };

        if (existingDefaultIndex >= 0)
        {
            merged[existingDefaultIndex] = installerDefault;
        }
        else
        {
            merged.Add(installerDefault);
        }

        var activeProfile = existing.ActiveProfile;
        if (string.IsNullOrWhiteSpace(activeProfile) ||
            !merged.Any(item =>
                item.Enabled &&
                string.Equals(
                    item.Name,
                    activeProfile,
                    StringComparison.OrdinalIgnoreCase)))
        {
            activeProfile = defaultName;
        }

        return new FilesProfilesDocument
        {
            SchemaVersion = "2.0",
            ActiveProfile = activeProfile,
            Profiles = merged
        };
    }

    private sealed class FilesProfilesDocument
    {
        public string SchemaVersion { get; set; } = "2.0";
        public string? ActiveProfile { get; set; }
        public List<FilesProfileDocumentEntry> Profiles { get; set; } = new();
    }

    private sealed class FilesProfileDocumentEntry
    {
        public string Name { get; set; } = string.Empty;
        public string Root { get; set; } = string.Empty;
        public string Mode { get; set; } = "read-only";
        public string Description { get; set; } = string.Empty;
        public bool Enabled { get; set; } = true;
        public bool AuthorizedByUser { get; set; }
        public DateTimeOffset? AuthorizedAt { get; set; }
        public string AuthorizationSource { get; set; } = string.Empty;
    }

    private static void Validate(
        FilesIntegrationOptions options)
    {
        if (!File.Exists(options.PythonExecutable))
        {
            throw new FileNotFoundException(
                "Files Python runtime was not found.",
                options.PythonExecutable);
        }

        if (!Directory.Exists(options.EngineRoot))
        {
            throw new DirectoryNotFoundException(
                $"Files engine root was not found: {options.EngineRoot}");
        }

        if (options.Port is < 1 or > 65535)
        {
            throw new ArgumentOutOfRangeException(
                nameof(options),
                "Files port is invalid.");
        }

        if (!IPAddressLoopback(options.BindHost))
        {
            throw new ArgumentException(
                "Files bind host must be loopback.",
                nameof(options));
        }

        if (string.IsNullOrWhiteSpace(options.DefaultProfileName))
        {
            throw new ArgumentException(
                "Default Files profile name is required.",
                nameof(options));
        }

        if (options.DefaultProfileMode is not ("read-only" or "read-write"))
        {
            throw new ArgumentException(
                "Default Files profile mode must be read-only or read-write.",
                nameof(options));
        }
    }

    private static bool IPAddressLoopback(string host) =>
        string.Equals(host, "localhost", StringComparison.OrdinalIgnoreCase) ||
        (System.Net.IPAddress.TryParse(host, out var ip) &&
            System.Net.IPAddress.IsLoopback(ip));
}
