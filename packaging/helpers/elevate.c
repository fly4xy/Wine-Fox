/*
 * elevate.exe of Wine Fox: runs its command line as administrator in Wine. Its manifest asks for
 * requireAdministrator, so Wine starts it with a full (elevated) token, and the program it starts
 * inherits that token, the console and the handles: the command line stays in its terminal.
 *
 *   wine elevate.exe cmd /k ...      ->  cmd as administrator, its exit code
 */
#include <windows.h>
#include <stdio.h>

/* the command line after this program's own name, quoting as it was */
static WCHAR *rest_of_line(WCHAR *line)
{
    if (*line == '"')
    {
        line++;
        while (*line && *line != '"') line++;
        if (*line) line++;
    }
    else while (*line && *line != ' ' && *line != '\t') line++;
    while (*line == ' ' || *line == '\t') line++;
    return line;
}

int wmain(void)
{
    WCHAR *command = rest_of_line(GetCommandLineW());
    STARTUPINFOW si = { sizeof(si) };
    PROCESS_INFORMATION pi;
    DWORD code = 1;

    if (!*command)
    {
        fwprintf(stderr, L"elevate.exe <program> [arguments]: runs it as administrator\n");
        return 2;
    }
    if (!CreateProcessW(NULL, command, NULL, NULL, TRUE, 0, NULL, NULL, &si, &pi))
    {
        fwprintf(stderr, L"elevate.exe: cannot start %ls (error %lu)\n", command, GetLastError());
        return 1;
    }
    WaitForSingleObject(pi.hProcess, INFINITE);
    GetExitCodeProcess(pi.hProcess, &code);
    CloseHandle(pi.hThread);
    CloseHandle(pi.hProcess);
    return (int)code;
}
