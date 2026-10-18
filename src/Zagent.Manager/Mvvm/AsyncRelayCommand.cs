using System.Windows.Input;

namespace Zagent.Manager.Mvvm;

public sealed class AsyncRelayCommand : ICommand
{
    private readonly Func<object?, Task> _execute;
    private readonly Func<object?, bool>? _canExecute;
    private int _running;

    public AsyncRelayCommand(
        Func<Task> execute,
        Func<bool>? canExecute = null)
        : this(
            _ => execute(),
            canExecute is null
                ? null
                : _ => canExecute())
    {
    }

    public AsyncRelayCommand(
        Func<object?, Task> execute,
        Func<object?, bool>? canExecute = null)
    {
        _execute = execute ??
            throw new ArgumentNullException(nameof(execute));
        _canExecute = canExecute;
    }

    public event EventHandler? CanExecuteChanged;

    public bool CanExecute(object? parameter) =>
        Volatile.Read(ref _running) == 0 &&
        (_canExecute?.Invoke(parameter) ?? true);

    public async void Execute(object? parameter)
    {
        if (!CanExecute(parameter))
        {
            return;
        }

        Interlocked.Exchange(ref _running, 1);
        RaiseCanExecuteChanged();

        try
        {
            await _execute(parameter);
        }
        finally
        {
            Interlocked.Exchange(ref _running, 0);
            RaiseCanExecuteChanged();
        }
    }

    public void RaiseCanExecuteChanged() =>
        CanExecuteChanged?.Invoke(
            this,
            EventArgs.Empty);
}
