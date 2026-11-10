"""Optional Windows Credential Manager storage scoped to this application."""

from .profiles import ProfileError

SERVICE = "AI Japanese Interview Assistant"
ACCOUNT = "OpenAI API Key"


def credential(operation, value=""):
    from keyring.backends.Windows import WinVaultKeyring
    from keyring.errors import PasswordDeleteError

    vault = WinVaultKeyring()
    try:
        match operation:
            case "read":
                return vault.get_password(SERVICE, ACCOUNT) or ""
            case "save":
                if not value:
                    raise ProfileError("请输入要保存的 API Key。")
                vault.set_password(SERVICE, ACCOUNT, value)
            case "delete":
                vault.delete_password(SERVICE, ACCOUNT)
            case _:
                raise ValueError("Unknown credential operation")
    except PasswordDeleteError:
        return ""
