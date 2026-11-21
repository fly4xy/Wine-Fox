/*
 * explorer.exe of Wine Fox: "open file location" and "open folder" from Windows programs show
 * the place in the Linux file manager (org.freedesktop.FileManager1 over D-Bus: Dolphin,
 * Nautilus..., the file selected; xdg-open when that is not there). Everything else (the
 * desktop, the tray, explorer without a place) goes on to Wine's own explorer, which Wine Fox
 * keeps as C:\windows\winefox\explorer.exe (this file is the prefix's native explorer.exe).
 *
 *   explorer.exe /select,"C:\x\a.txt"    explorer.exe C:\x    explorer.exe /e,/root,C:\x
 */
#include <windows.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <wchar.h>

typedef char *(__cdecl *unix_name_fn)(const WCHAR *dos);
typedef LONG (WINAPI *set_info_fn)(HANDLE process, ULONG info_class, void *info, ULONG size);
typedef LONG (WINAPI *spawn_fn)(char *const argv[], int wait);      /* stdcall on 32 bits */

/* the place in explorer's arguments: /select,<file> (select: TRUE), or a folder or file named
 * plainly or after /e, /n, /root; NULL for the desktop, the tray and the like */
static WCHAR *place(WCHAR *line, BOOL *select)
{
    WCHAR *args = line, *found = NULL, *token, *context = NULL;
    static WCHAR result[MAX_PATH * 2];

    /* skip the program's own name */
    if (*args == '"') { args++; while (*args && *args != '"') args++; if (*args) args++; }
    else while (*args && *args != ' ' && *args != '\t') args++;

    *select = FALSE;
    for (token = wcstok(args, L",", &context); token; token = wcstok(NULL, L",", &context))
    {
        WCHAR *t = token, *end;
        while (*t == ' ' || *t == '\t') t++;
        end = t + wcslen(t);
        while (end > t && (end[-1] == ' ' || end[-1] == '\t')) *--end = 0;
        /* "/select,C:\a b.txt" quoted whole too: the quotes go wherever they are */
        if (*t == '"') t++;
        if (end > t && end[-1] == '"') *--end = 0;
        if (!*t) continue;
        if (!_wcsicmp(t, L"/select")) { *select = TRUE; continue; }
        if (!_wcsnicmp(t, L"/desktop", 8) || !_wcsnicmp(t, L"/systray", 8) || !_wcsicmp(t, L"/shell")) return NULL;
        if (t[0] == '/') continue;                  /* /e, /n, /root and the like */
        found = t;
        if (*select) break;
    }
    if (!found) return NULL;
    lstrcpynW(result, found, ARRAYSIZE(result));
    return result;
}

/* file:///a%20b/c: the path as a URI, its bytes percent-encoded but for / and the unreserved */
static char *file_uri(const char *path)
{
    static const char keep[] = "-._~/";
    char *out = malloc(strlen(path) * 3 + 8), *o = out;
    o += sprintf(o, "file://");
    for (; *path; path++)
    {
        unsigned char c = *path;
        if ((c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9') || strchr(keep, c))
            *o++ = c;
        else o += sprintf(o, "%%%02X", c);
    }
    *o = 0;
    return out;
}

/* Wine's own explorer for whatever this one does not do; never this one again */
static int wine_explorer(void)
{
    STARTUPINFOW si = { sizeof(si) };
    PROCESS_INFORMATION pi;
    WCHAR path[MAX_PATH];
    DWORD code = 1, got = 0;
    HANDLE last = NULL;
    set_info_fn set_info = (set_info_fn)GetProcAddress(GetModuleHandleW(L"ntdll.dll"), "NtSetInformationProcess");
    char head[0x50] = { 0 };
    HANDLE file;

    GetWindowsDirectoryW(path, MAX_PATH - 32);
    wcscat(path, L"\\winefox\\explorer.exe");
    /* only Wine's own file (its "Wine builtin DLL" mark), so that this one never runs itself */
    file = CreateFileW(path, GENERIC_READ, FILE_SHARE_READ, NULL, OPEN_EXISTING, 0, NULL);
    if (file == INVALID_HANDLE_VALUE) return 1;
    ReadFile(file, head, sizeof(head), &got, NULL);
    CloseHandle(file);
    if (got < sizeof(head) || memcmp(head + 0x40, "Wine builtin DLL", 16)) return 1;
    if (!CreateProcessW(path, GetCommandLineW(), NULL, NULL, TRUE, 0, NULL, NULL, &si, &pi))
        return 1;
    /* waiting for it as Wine's own explorer would run: a system process, so that the prefix
     * still ends with its last program (Wine signals `last` then) */
    if (set_info && !set_info(GetCurrentProcess(), 1000 /* ProcessWineMakeProcessSystem */, &last, sizeof(HANDLE *)))
    {
        HANDLE both[2] = { pi.hProcess, last };
        if (WaitForMultipleObjects(2, both, FALSE, INFINITE) == WAIT_OBJECT_0 + 1) return 0;
    }
    else WaitForSingleObject(pi.hProcess, INFINITE);
    GetExitCodeProcess(pi.hProcess, &code);
    return (int)code;
}

int WINAPI wWinMain(HINSTANCE instance, HINSTANCE previous, WCHAR *cmdline, int show)
{
    HMODULE ntdll = GetModuleHandleW(L"ntdll.dll"), kernel32 = GetModuleHandleW(L"kernel32.dll");
    spawn_fn spawn = (spawn_fn)GetProcAddress(ntdll, "__wine_unix_spawnvp");
    unix_name_fn unix_name = (unix_name_fn)GetProcAddress(kernel32, "wine_get_unix_file_name");
    WCHAR *line = _wcsdup(GetCommandLineW()), *where;
    BOOL select;
    char *path, *uri, *folder, *slash;

    where = place(line, &select);
    if (!where || !spawn || !unix_name || !(path = unix_name(where))) return wine_explorer();
    if (GetFileAttributesW(where) == INVALID_FILE_ATTRIBUTES) return wine_explorer();
    uri = file_uri(path);
    {
        /* the host's programs, without Wine's libraries in their way */
        char item[8192];
        char *show[] = { "/usr/bin/env", "-u", "LD_LIBRARY_PATH", "-u", "LD_PRELOAD", "dbus-send", "--session",
                         "--print-reply", "--dest=org.freedesktop.FileManager1", "--type=method_call",
                         "/org/freedesktop/FileManager1",
                         select ? "org.freedesktop.FileManager1.ShowItems" : "org.freedesktop.FileManager1.ShowFolders",
                         item, "string:", NULL };
        snprintf(item, sizeof(item), "array:string:%s", uri);
        if (spawn(show, 1) == 0) return 0;
    }
    /* no FileManager1: the folder (of the file) with xdg-open */
    folder = _strdup(path);
    if (select && (slash = strrchr(folder, '/')) && slash != folder) *slash = 0;
    {
        char *open[] = { "/usr/bin/env", "-u", "LD_LIBRARY_PATH", "-u", "LD_PRELOAD", "xdg-open", folder, NULL };
        spawn(open, 0);
    }
    return 0;
}
