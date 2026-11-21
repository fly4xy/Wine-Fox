/*
 * wininspect: watches the windows of a Wine prefix to debug window, focus and
 * drag-and-drop problems (for example in Unreal Editor).
 *
 * Run it in the same prefix as the application:
 *   wine wininspect.exe [--process NAME] [--verbose] [--log FILE]
 *
 * It logs top-level windows appearing, disappearing and changing, the foreground
 * window and the focus. Press Ctrl+Shift+F12 to dump the window under the mouse
 * cursor with its parents and owners.
 *
 * Build: x86_64-w64-mingw32-gcc -municode -O2 -o wininspect.exe wininspect.c -lpsapi -lshlwapi
 */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <psapi.h>
#include <shlwapi.h>
#include <stdio.h>
#include <wchar.h>

#define HOTKEY_ID 1
#define MAX_TRACKED 4096

struct tracked
{
    HWND hwnd;
    BOOL visible;
    DWORD style, exstyle;
    RECT rect;
    WCHAR title[128];
    BOOL seen;
};

static struct tracked tracked[MAX_TRACKED];
static unsigned int tracked_count;
static const WCHAR *process_filter;
static BOOL verbose;
static FILE *log_file;
static DWORD self_pid;

static void out(const WCHAR *fmt, ...)
{
    WCHAR buf[2048];
    SYSTEMTIME t;
    va_list args;
    int len;

    GetLocalTime(&t);
    len = swprintf(buf, ARRAYSIZE(buf), L"%02u:%02u:%02u.%03u ", t.wHour, t.wMinute, t.wSecond, t.wMilliseconds);
    va_start(args, fmt);
    vswprintf(buf + len, ARRAYSIZE(buf) - len, fmt, args);
    va_end(args);

    wprintf(L"%ls\n", buf);
    fflush(stdout);
    if (log_file)
    {
        fwprintf(log_file, L"%ls\n", buf);
        fflush(log_file);
    }
}

static void process_name(DWORD pid, WCHAR *name, DWORD size)
{
    HANDLE process = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, FALSE, pid);
    WCHAR path[MAX_PATH], *p;
    DWORD len = ARRAYSIZE(path);

    lstrcpynW(name, L"?", size);
    if (!process) return;
    if (QueryFullProcessImageNameW(process, 0, path, &len))
    {
        p = wcsrchr(path, '\\');
        lstrcpynW(name, p ? p + 1 : path, size);
    }
    CloseHandle(process);
}

static BOOL window_matches(HWND hwnd)
{
    WCHAR name[MAX_PATH];
    DWORD pid;

    GetWindowThreadProcessId(hwnd, &pid);
    if (pid == self_pid) return FALSE;
    if (!process_filter) return TRUE;
    process_name(pid, name, ARRAYSIZE(name));
    return StrStrIW(name, process_filter) != NULL;
}

struct flag { DWORD value; const WCHAR *name; };

static const struct flag styles[] =
{
    { WS_POPUP, L"POPUP" }, { WS_CHILD, L"CHILD" }, { WS_MINIMIZE, L"MINIMIZE" },
    { WS_VISIBLE, L"VISIBLE" }, { WS_DISABLED, L"DISABLED" }, { WS_CLIPSIBLINGS, L"CLIPSIBLINGS" },
    { WS_CLIPCHILDREN, L"CLIPCHILDREN" }, { WS_MAXIMIZE, L"MAXIMIZE" }, { WS_BORDER, L"BORDER" },
    { WS_DLGFRAME, L"DLGFRAME" }, { WS_SYSMENU, L"SYSMENU" }, { WS_THICKFRAME, L"THICKFRAME" },
    { WS_MINIMIZEBOX, L"MINIMIZEBOX" }, { WS_MAXIMIZEBOX, L"MAXIMIZEBOX" }, { 0 }
};

static const struct flag exstyles[] =
{
    { WS_EX_DLGMODALFRAME, L"DLGMODALFRAME" }, { WS_EX_TOPMOST, L"TOPMOST" },
    { WS_EX_ACCEPTFILES, L"ACCEPTFILES" }, { WS_EX_TRANSPARENT, L"TRANSPARENT" },
    { WS_EX_TOOLWINDOW, L"TOOLWINDOW" }, { WS_EX_WINDOWEDGE, L"WINDOWEDGE" },
    { WS_EX_APPWINDOW, L"APPWINDOW" }, { WS_EX_LAYERED, L"LAYERED" },
    { WS_EX_NOACTIVATE, L"NOACTIVATE" }, { WS_EX_COMPOSITED, L"COMPOSITED" }, { 0 }
};

static void format_flags(WCHAR *buf, size_t size, DWORD value, const struct flag *flags)
{
    const struct flag *f;
    size_t len;

    len = swprintf(buf, size, L"%08lx", value);
    for (f = flags; f->value && len < size; f++)
        if ((value & f->value) == f->value)
            len += swprintf(buf + len, size - len, L" %ls", f->name);
}

static const WCHAR *describe(HWND hwnd, WCHAR *buf, size_t size)
{
    WCHAR cls[128] = L"", title[128] = L"", name[64];
    DWORD pid, tid;

    if (!hwnd) return L"(none)";
    GetClassNameW(hwnd, cls, ARRAYSIZE(cls));
    GetWindowTextW(hwnd, title, ARRAYSIZE(title));
    tid = GetWindowThreadProcessId(hwnd, &pid);
    process_name(pid, name, ARRAYSIZE(name));
    swprintf(buf, size, L"%p [%ls] \"%ls\" (%ls pid %lu tid %lu)", hwnd, cls, title, name, pid, tid);
    return buf;
}

static void dump_window(HWND hwnd, const WCHAR *prefix)
{
    WCHAR desc[512], style[256], exstyle[256], owner[512], parent[512];
    RECT rect;
    HANDLE xid, droptarget;

    GetWindowRect(hwnd, &rect);
    format_flags(style, ARRAYSIZE(style), GetWindowLongW(hwnd, GWL_STYLE), styles);
    format_flags(exstyle, ARRAYSIZE(exstyle), GetWindowLongW(hwnd, GWL_EXSTYLE), exstyles);
    xid = GetPropW(GetAncestor(hwnd, GA_ROOT), L"__wine_x11_whole_window");
    droptarget = GetPropW(hwnd, L"WineMarshalledDropTarget");

    out(L"%ls%ls", prefix, describe(hwnd, desc, ARRAYSIZE(desc)));
    out(L"%ls    rect (%ld,%ld)-(%ld,%ld) %ldx%ld, visible %d, enabled %d, iconic %d, zoomed %d",
        prefix, rect.left, rect.top, rect.right, rect.bottom, rect.right - rect.left,
        rect.bottom - rect.top, IsWindowVisible(hwnd), IsWindowEnabled(hwnd), IsIconic(hwnd), IsZoomed(hwnd));
    out(L"%ls    style   %ls", prefix, style);
    out(L"%ls    exstyle %ls", prefix, exstyle);
    out(L"%ls    owner   %ls", prefix, describe(GetWindow(hwnd, GW_OWNER), owner, ARRAYSIZE(owner)));
    out(L"%ls    parent  %ls", prefix, describe(GetAncestor(hwnd, GA_PARENT) == GetDesktopWindow()
                                                ? NULL : GetAncestor(hwnd, GA_PARENT), parent, ARRAYSIZE(parent)));
    out(L"%ls    x11 window 0x%Ix, OLE drop target %ls", prefix, (ULONG_PTR)xid,
        droptarget ? L"registered" : L"none");
}

static void dump_under_cursor(void)
{
    WCHAR desc[512];
    GUITHREADINFO info = { sizeof(info) };
    POINT pt;
    HWND hwnd, root, iter;

    GetCursorPos(&pt);
    hwnd = WindowFromPoint(pt);
    out(L"===== window under cursor at %ld,%ld =====", pt.x, pt.y);
    if (!hwnd)
    {
        out(L"(no window)");
        return;
    }
    dump_window(hwnd, L"");

    root = GetAncestor(hwnd, GA_ROOT);
    for (iter = GetAncestor(hwnd, GA_PARENT); iter && iter != GetDesktopWindow(); iter = GetAncestor(iter, GA_PARENT))
        dump_window(iter, L"  parent: ");
    for (iter = GetWindow(root, GW_OWNER); iter; iter = GetWindow(iter, GW_OWNER))
        dump_window(iter, L"  owner: ");

    if (GetGUIThreadInfo(GetWindowThreadProcessId(hwnd, NULL), &info))
    {
        out(L"  thread active  %ls", describe(info.hwndActive, desc, ARRAYSIZE(desc)));
        out(L"  thread focus   %ls", describe(info.hwndFocus, desc, ARRAYSIZE(desc)));
        out(L"  thread capture %ls", describe(info.hwndCapture, desc, ARRAYSIZE(desc)));
    }
    out(L"  foreground     %ls", describe(GetForegroundWindow(), desc, ARRAYSIZE(desc)));
    out(L"===========================================");
}

static struct tracked *find_tracked(HWND hwnd)
{
    unsigned int i;

    for (i = 0; i < tracked_count; i++) if (tracked[i].hwnd == hwnd) return &tracked[i];
    return NULL;
}

static BOOL CALLBACK enum_proc(HWND hwnd, LPARAM lparam)
{
    WCHAR desc[512], style[256], exstyle[256];
    struct tracked *t = find_tracked(hwnd), now = { hwnd };
    BOOL first = (BOOL)lparam;

    if (!t && !window_matches(hwnd)) return TRUE;

    now.visible = IsWindowVisible(hwnd);
    now.style = GetWindowLongW(hwnd, GWL_STYLE);
    now.exstyle = GetWindowLongW(hwnd, GWL_EXSTYLE);
    GetWindowRect(hwnd, &now.rect);
    GetWindowTextW(hwnd, now.title, ARRAYSIZE(now.title));
    now.seen = TRUE;

    if (!t)
    {
        if (tracked_count == MAX_TRACKED) return TRUE;
        t = &tracked[tracked_count++];
        *t = now;
        if (first ? now.visible : (now.visible || verbose))
        {
            out(L"%ls %ls", first ? L"EXISTS " : L"CREATED", describe(hwnd, desc, ARRAYSIZE(desc)));
            if (!first || verbose) dump_window(hwnd, L"        ");
        }
        return TRUE;
    }

    if (now.visible != t->visible)
    {
        out(L"%ls  %ls", now.visible ? L"SHOWN " : L"HIDDEN", describe(hwnd, desc, ARRAYSIZE(desc)));
        if (now.visible) dump_window(hwnd, L"        ");
    }
    else if (now.visible && (now.style != t->style || now.exstyle != t->exstyle))
    {
        format_flags(style, ARRAYSIZE(style), now.style, styles);
        format_flags(exstyle, ARRAYSIZE(exstyle), now.exstyle, exstyles);
        out(L"STYLE   %ls\n        style %ls\n        exstyle %ls", describe(hwnd, desc, ARRAYSIZE(desc)), style, exstyle);
    }
    if (now.visible && lstrcmpW(now.title, t->title))
        out(L"TITLE   %ls", describe(hwnd, desc, ARRAYSIZE(desc)));
    if (verbose && now.visible && !EqualRect(&now.rect, &t->rect))
        out(L"MOVED   %p (%ld,%ld)-(%ld,%ld)", hwnd, now.rect.left, now.rect.top, now.rect.right, now.rect.bottom);
    *t = now;
    return TRUE;
}

static void poll_windows(BOOL first)
{
    unsigned int i, j;

    for (i = 0; i < tracked_count; i++) tracked[i].seen = FALSE;
    EnumWindows(enum_proc, first);
    for (i = j = 0; i < tracked_count; i++)
    {
        if (!tracked[i].seen)
        {
            if (tracked[i].visible || verbose)
                out(L"DESTROY %p [\"%ls\"]", tracked[i].hwnd, tracked[i].title);
            continue;
        }
        tracked[j++] = tracked[i];
    }
    tracked_count = j;
}

static void poll_focus(void)
{
    static HWND last_fg, last_active, last_focus, last_capture;
    GUITHREADINFO info = { sizeof(info) };
    WCHAR desc[512];
    HWND fg = GetForegroundWindow();

    if (fg != last_fg)
    {
        out(L"FOREGROUND %ls", describe(fg, desc, ARRAYSIZE(desc)));
        last_fg = fg;
    }
    if (!fg || !GetGUIThreadInfo(GetWindowThreadProcessId(fg, NULL), &info)) return;
    if (info.hwndActive != last_active)
        out(L"ACTIVE     %ls", describe(last_active = info.hwndActive, desc, ARRAYSIZE(desc)));
    if (info.hwndFocus != last_focus)
        out(L"FOCUS      %ls", describe(last_focus = info.hwndFocus, desc, ARRAYSIZE(desc)));
    if (info.hwndCapture != last_capture)
        out(L"CAPTURE    %ls", describe(last_capture = info.hwndCapture, desc, ARRAYSIZE(desc)));
}

int wmain(int argc, WCHAR **argv)
{
    const WCHAR *log_path = L"wininspect.log";
    MSG msg;
    int i;

    for (i = 1; i < argc; i++)
    {
        if (!lstrcmpW(argv[i], L"--process") && i + 1 < argc) process_filter = argv[++i];
        else if (!lstrcmpW(argv[i], L"--log") && i + 1 < argc) log_path = argv[++i];
        else if (!lstrcmpW(argv[i], L"--verbose") || !lstrcmpW(argv[i], L"-v")) verbose = TRUE;
        else
        {
            wprintf(L"usage: wininspect [--process NAME] [--verbose] [--log FILE]\n"
                    L"  Ctrl+Shift+F12 dumps the window under the mouse cursor.\n");
            return 1;
        }
    }

    self_pid = GetCurrentProcessId();
    log_file = _wfopen(log_path, L"w, ccs=UTF-8");
    if (!RegisterHotKey(NULL, HOTKEY_ID, MOD_CONTROL | MOD_SHIFT | MOD_NOREPEAT, VK_F12))
        out(L"warning: could not register Ctrl+Shift+F12 (error %lu)", GetLastError());

    out(L"wininspect: watching %ls, logging to %ls; Ctrl+Shift+F12 dumps the window under the cursor",
        process_filter ? process_filter : L"all processes", log_path);
    poll_windows(TRUE);
    SetTimer(NULL, 0, 100, NULL);

    while (GetMessageW(&msg, NULL, 0, 0))
    {
        if (msg.message == WM_HOTKEY && msg.wParam == HOTKEY_ID) dump_under_cursor();
        else if (msg.message == WM_TIMER)
        {
            poll_windows(FALSE);
            poll_focus();
        }
        DispatchMessageW(&msg);
    }
    return 0;
}
