using System.Collections.ObjectModel;
using Zagent.Shared.Manager;

namespace Zagent.Manager.ViewModels;

public sealed class ChatColumnViewModel
{
    public ChatColumnViewModel(
        string sessionId,
        string title,
        IEnumerable<ManagerChatLogRow> entries)
    {
        SessionId = sessionId;
        Title = title;
        Entries = new ObservableCollection<
            ManagerChatLogRow>(entries);
    }

    public string SessionId { get; }

    public string Title { get; }

    public ObservableCollection<ManagerChatLogRow> Entries { get; }
}
