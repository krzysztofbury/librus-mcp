"""Read credential files through pinned Win32 handles with conservative ACL checks."""

from pathlib import Path
from typing import Any, cast

import pywintypes  # type: ignore[import-untyped]
import win32api  # type: ignore[import-untyped]
import win32con  # type: ignore[import-untyped]
import win32file  # type: ignore[import-untyped]
import win32security  # type: ignore[import-untyped]

from librus_mcp.config import ConfigError


def validate_acl(handle: Any) -> None:
    token = win32security.OpenProcessToken(win32api.GetCurrentProcess(), win32con.TOKEN_QUERY)
    try:
        user = win32security.ConvertSidToStringSid(
            win32security.GetTokenInformation(token, win32security.TokenUser)[0]
        )
        owner = win32security.ConvertSidToStringSid(
            win32security.GetTokenInformation(token, win32security.TokenOwner)
        )
    finally:
        token.Close()
    security = win32security.GetSecurityInfo(
        handle,
        win32security.SE_FILE_OBJECT,
        win32security.OWNER_SECURITY_INFORMATION | win32security.DACL_SECURITY_INFORMATION,
    )
    acl = security.GetSecurityDescriptorDacl()
    if (
        win32security.ConvertSidToStringSid(security.GetSecurityDescriptorOwner())
        not in {user, owner}
        or acl is None
        or not 1 <= acl.GetAceCount() <= 16
    ):
        raise ConfigError("configuration must have an owner-private Windows ACL")
    for index in range(acl.GetAceCount()):
        ace = acl.GetAce(index)
        if (
            len(ace) != 3
            or ace[0][0] != win32security.ACCESS_ALLOWED_ACE_TYPE
            or win32security.ConvertSidToStringSid(ace[2]) not in {user, "S-1-5-18", "S-1-5-32-544"}
        ):
            raise ConfigError("configuration must have an owner-private Windows ACL")


def read_private_config(path: Path, maximum: int) -> bytes:
    # This module is loaded only by the Windows configuration read boundary.
    path = path.absolute()
    if (
        len(path.drive) != 2
        or path.drive[1] != ":"
        or len(path.parts) > 128
        or any(part in {".", ".."} or ":" in part for part in path.parts[1:])
    ):
        raise ConfigError("configuration requires a local fixed NTFS path")
    handles: list[Any] = []
    try:
        if win32file.GetDriveType(path.anchor) != win32con.DRIVE_FIXED:
            raise ConfigError("configuration requires a local fixed NTFS path")
        volume = win32api.GetVolumeInformation(path.anchor)
        if volume[4].upper() != "NTFS" or not volume[3] & win32con.FILE_PERSISTENT_ACLS:
            raise ConfigError("configuration requires a local fixed NTFS path")
        # Deny rename/deletion while traversing. Reparse points in any component
        # are not credential sources, even if their final target appears private.
        for parent in reversed(path.parents):
            handle = win32file.CreateFile(
                str(parent),
                0x80,
                win32con.FILE_SHARE_READ | win32con.FILE_SHARE_WRITE,
                None,
                win32con.OPEN_EXISTING,
                win32con.FILE_FLAG_BACKUP_SEMANTICS | win32file.FILE_FLAG_OPEN_REPARSE_POINT,
                None,
            )
            handles.append(handle)
            attributes = win32file.GetFileInformationByHandle(handle)[0]
            if (
                not attributes & win32con.FILE_ATTRIBUTE_DIRECTORY
                or attributes & win32con.FILE_ATTRIBUTE_REPARSE_POINT
            ):
                raise ConfigError("configuration path must not contain reparse points")
        handle = win32file.CreateFile(
            str(path),
            win32con.GENERIC_READ | win32con.READ_CONTROL,
            win32con.FILE_SHARE_READ,
            None,
            win32con.OPEN_EXISTING,
            win32file.FILE_FLAG_OPEN_REPARSE_POINT,
            None,
        )
        handles.append(handle)
        info = win32file.GetFileInformationByHandle(handle)
        if (
            info[0] & (win32con.FILE_ATTRIBUTE_DIRECTORY | win32con.FILE_ATTRIBUTE_REPARSE_POINT)
            or info[7] != 1
            or win32file.GetFileType(handle) != win32con.FILE_TYPE_DISK
        ):
            raise ConfigError("configuration must be a regular unlinked file")
        validate_acl(handle)
        if ((info[5] << 32) | info[6]) > maximum:
            raise ConfigError("configuration file exceeds the configuration size limit")
        if not info[5] and not info[6]:
            return b""
        _, body = win32file.ReadFile(handle, maximum + 1)
        return cast(bytes, body)
    except pywintypes.error:
        raise ConfigError(
            "cannot read configuration file; check its path and private Windows ACL"
        ) from None
    finally:
        for handle in reversed(handles):
            handle.Close()
