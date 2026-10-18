using Zagent.Shared.Paths;

namespace Zagent.Core.Paths;

public interface IBasePathResolver
{
    ZagentPathLayout Resolve(
        string installRoot,
        string? filesDefaultProfile = null,
        string? dataRoot = null);
}
