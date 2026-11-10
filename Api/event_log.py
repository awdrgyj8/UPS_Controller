"""簡易事件記錄：保留原本 print 到 console 的行為，同時把訊息轉送給 Web 介面的事件紀錄。"""

_hooks = []


def add_hook(hook):
    if hook not in _hooks:
        _hooks.append(hook)


def remove_hook(hook):
    if hook in _hooks:
        _hooks.remove(hook)


def _guess_level(message):
    if message.startswith("❌"):
        return "error"
    if message.startswith("⚠️"):
        return "warning"
    if message.startswith("✅"):
        return "success"
    return "info"


def log(message, level=None, source="system"):
    print(message)
    level = level or _guess_level(message)
    for hook in list(_hooks):
        try:
            hook(level, source, message)
        except Exception:
            pass
