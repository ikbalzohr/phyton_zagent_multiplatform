using System.ComponentModel;
using System.Diagnostics;
using System.Runtime.InteropServices;
using Microsoft.Win32.SafeHandles;

namespace Zagent.Core.Supervision;

internal sealed class WindowsJobObject : IDisposable
{
    private const uint JobObjectLimitKillOnJobClose = 0x00002000;
    private readonly SafeFileHandle _handle;
    private int _disposed;

    private WindowsJobObject(SafeFileHandle handle)
    {
        _handle = handle;
    }

    public static bool TryCreateAndAssign(
        Process process,
        out WindowsJobObject? job,
        out string? error)
    {
        ArgumentNullException.ThrowIfNull(process);

        job = null;
        error = null;

        if (!OperatingSystem.IsWindows())
        {
            error = "Windows Job Objects are only available on Windows.";
            return false;
        }

        var rawHandle = NativeMethods.CreateJobObject(
            IntPtr.Zero,
            null);

        if (rawHandle == IntPtr.Zero)
        {
            error = new Win32Exception(
                Marshal.GetLastWin32Error()).Message;
            return false;
        }

        var safeHandle = new SafeFileHandle(
            rawHandle,
            ownsHandle: true);

        try
        {
            var limits = new JobObjectExtendedLimitInformation
            {
                BasicLimitInformation =
                {
                    LimitFlags = JobObjectLimitKillOnJobClose
                }
            };

            var length = Marshal.SizeOf<JobObjectExtendedLimitInformation>();
            var buffer = Marshal.AllocHGlobal(length);

            try
            {
                Marshal.StructureToPtr(
                    limits,
                    buffer,
                    fDeleteOld: false);

                if (!NativeMethods.SetInformationJobObject(
                        safeHandle.DangerousGetHandle(),
                        JobObjectInfoType.ExtendedLimitInformation,
                        buffer,
                        (uint)length))
                {
                    error = new Win32Exception(
                        Marshal.GetLastWin32Error()).Message;
                    return false;
                }
            }
            finally
            {
                Marshal.FreeHGlobal(buffer);
            }

            if (!NativeMethods.AssignProcessToJobObject(
                    safeHandle.DangerousGetHandle(),
                    process.Handle))
            {
                error = new Win32Exception(
                    Marshal.GetLastWin32Error()).Message;
                return false;
            }

            job = new WindowsJobObject(safeHandle);
            safeHandle = null!;
            return true;
        }
        finally
        {
            safeHandle?.Dispose();
        }
    }

    public void Dispose()
    {
        if (Interlocked.Exchange(ref _disposed, 1) != 0)
        {
            return;
        }

        _handle.Dispose();
    }

    private enum JobObjectInfoType
    {
        ExtendedLimitInformation = 9
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct IoCounters
    {
        public ulong ReadOperationCount;
        public ulong WriteOperationCount;
        public ulong OtherOperationCount;
        public ulong ReadTransferCount;
        public ulong WriteTransferCount;
        public ulong OtherTransferCount;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct JobObjectBasicLimitInformation
    {
        public long PerProcessUserTimeLimit;
        public long PerJobUserTimeLimit;
        public uint LimitFlags;
        public UIntPtr MinimumWorkingSetSize;
        public UIntPtr MaximumWorkingSetSize;
        public uint ActiveProcessLimit;
        public UIntPtr Affinity;
        public uint PriorityClass;
        public uint SchedulingClass;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct JobObjectExtendedLimitInformation
    {
        public JobObjectBasicLimitInformation BasicLimitInformation;
        public IoCounters IoInfo;
        public UIntPtr ProcessMemoryLimit;
        public UIntPtr JobMemoryLimit;
        public UIntPtr PeakProcessMemoryUsed;
        public UIntPtr PeakJobMemoryUsed;
    }

    private static class NativeMethods
    {
        [DllImport(
            "kernel32.dll",
            EntryPoint = "CreateJobObjectW",
            CharSet = CharSet.Unicode,
            SetLastError = true)]
        internal static extern IntPtr CreateJobObject(
            IntPtr jobAttributes,
            string? name);

        [DllImport(
            "kernel32.dll",
            SetLastError = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        internal static extern bool SetInformationJobObject(
            IntPtr job,
            JobObjectInfoType infoType,
            IntPtr info,
            uint infoLength);

        [DllImport(
            "kernel32.dll",
            SetLastError = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        internal static extern bool AssignProcessToJobObject(
            IntPtr job,
            IntPtr process);
    }
}
