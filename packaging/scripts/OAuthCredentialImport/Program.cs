using Zagent.Core.Manager;

// Only metadata/path arguments, never a secret. No product startup/build/network activity.
if (args.Length != 6 || args[0] != "--data-root" || args[2] != "--package" || args[4] != "--certificate-thumbprint")
{
    Console.Error.WriteLine("Usage: OAuthCredentialImport --data-root <owner-data-root> --package <ciphertext-json-path> --certificate-thumbprint <40-hex>");
    return 2;
}
try
{
    if (!OperatingSystem.IsWindows() || !Environment.UserInteractive)
        throw new InvalidDataException();
    OAuthIntrospectionCredentialStore.Import(args[1], OAuthIntrospectionCredentialStore.ReadPackage(args[3]), args[5]);
    Console.WriteLine("OAuth credential imported; CurrentUser DPAPI and owner-only ACL verified. Core restart required; no resource configuration or grants were changed.");
    return 0;
}
catch
{
    // Deliberately do not print exception details/stack/arguments or any package material.
    Console.Error.WriteLine("OAuth import rejected. No overwrite attempted. Inspect partial state metadata locally before retrying.");
    return 1;
}
