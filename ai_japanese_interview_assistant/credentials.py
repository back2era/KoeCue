"""Optional Windows Credential Manager storage scoped to this application."""

from .config import OPENAI
from .profiles import ProfileError

SERVICE = "AI Japanese Interview Assistant"


def credential(operation, value="", provider=OPENAI):
    from keyring.backends.Windows import WinVaultKeyring
    from keyring.errors import PasswordDeleteError

    vault = WinVaultKeyring()
    account = f"{provider.label} API Key"
    try:
        match operation:
            case "read":
                return vault.get_password(SERVICE, account) or ""
            case "save":
                if not value:
                    raise ProfileError("请输入要保存的 API Key。")
                vault.set_password(SERVICE, account, value)
            case "delete":
                vault.delete_password(SERVICE, account)
            case _:
                raise ValueError("Unknown credential operation")
    except PasswordDeleteError:
        return ""
