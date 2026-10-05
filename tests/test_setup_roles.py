"""Regression tests for /setup and the interaction-lifecycle rules it broke.

Deliberately source-parsing rather than import-based: config.py raises at import
time without DISCORD_TOKEN, and the suite must not need a live bot token.

Run with:
    python -m pytest tests/ -q

If pytest hangs during collection, a third-party plugin is auto-loading; use
    PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/ -q
"""
import ast
import os
import re

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ADMIN_PY = os.path.join(ROOT, "cogs", "admin.py")
CHECKS_PY = os.path.join(ROOT, "utils", "checks.py")


def read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def managed_roles():
    """Role names listed in cogs/admin.py MANAGED_ROLES."""
    tree = ast.parse(read(ADMIN_PY))
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name) and tgt.id == "MANAGED_ROLES":
                    return [e.value for e in node.value.elts if isinstance(e, ast.Constant)]
    raise AssertionError("MANAGED_ROLES not found in cogs/admin.py")


def gated_roles():
    """Role names referenced by utils/checks.py ROLE_* constants."""
    return set(re.findall(r'^ROLE_\w+ = "(.+)"', read(CHECKS_PY), re.M))


def setup_fn():
    """The /setup command callback inside the Admin cog."""
    tree = ast.parse(read(ADMIN_PY))
    for cls in [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]:
        for fn in [n for n in cls.body if isinstance(n, ast.AsyncFunctionDef)]:
            for d in fn.decorator_list:
                if isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute):
                    kw = {k.arg: k.value for k in d.keywords}
                    if "name" in kw and getattr(kw["name"], "value", None) == "setup":
                        return fn
    raise AssertionError("/setup command not found")


# --------------------------------------------------------------- role sync
def test_every_gated_role_is_created_by_setup():
    """A role that gates commands but isn't in MANAGED_ROLES locks those
    commands out permanently, and /setup reports success while doing so."""
    missing = sorted(gated_roles() - set(managed_roles()))
    assert not missing, (
        f"/setup does not create these gated roles: {missing}. "
        "Commands behind them can never be unlocked by a server owner."
    )


def test_managed_roles_have_no_duplicates():
    roles = managed_roles()
    assert len(roles) == len(set(roles)), "duplicate role names in MANAGED_ROLES"


def test_gated_roles_are_nonempty():
    """Guard against the test silently passing on a broken regex."""
    assert gated_roles(), "failed to parse ROLE_* constants from utils/checks.py"
    assert managed_roles(), "failed to parse MANAGED_ROLES from cogs/admin.py"


# ------------------------------------------------------- interaction safety
def test_setup_defers_before_first_write():
    """Discord expires an interaction after 3s; /setup makes ~20 REST calls
    and must defer before the first of them."""
    fn = setup_fn()
    defer_lines = [n.lineno for n in ast.walk(fn)
                   if isinstance(n, ast.Attribute) and n.attr == "defer"]
    assert defer_lines, "/setup never calls interaction.response.defer()"

    write_lines = [
        n.lineno for n in ast.walk(fn)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
        and n.func.attr in {"create_role", "create_text_channel"}
    ]
    assert write_lines, "no longer creates anything - update this test"
    assert min(defer_lines) < min(write_lines), (
        f"/setup calls create_* (line {min(write_lines)}) before defer "
        f"(line {min(defer_lines)})"
    )


def test_setup_does_not_swallow_exceptions():
    """Bare `except Exception: pass` made /setup report success while silently
    creating nothing."""
    fn = setup_fn()
    for node in ast.walk(fn):
        if isinstance(node, ast.ExceptHandler) and node.type is None:
            continue
        if isinstance(node, ast.ExceptHandler):
            body = node.body
            if len(body) == 1 and isinstance(body[0], ast.Pass):
                names = ast.unparse(node.type)
                raise AssertionError(
                    f"/setup silently swallows {names} at line {node.lineno}"
                )


def test_setup_replies_via_followup_when_deferred():
    """defer() answers the interaction; the real reply must use followup.send,
    not response.send_message (which would raise AlreadyResponded)."""
    fn = setup_fn()
    assert any(
        isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
        and n.func.attr == "send" and "followup" in ast.unparse(n.func)
        for n in ast.walk(fn)
    ), "/setup defers but never replies via followup.send"
    assert not any(
        isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
        and n.func.attr == "send_message" and "response" in ast.unparse(n.func)
        and n.lineno > min(x.lineno for x in ast.walk(fn)
                           if isinstance(x, ast.Attribute) and x.attr == "defer")
        for n in ast.walk(fn)
    ), "/setup defers then also calls response.send_message -> AlreadyResponded"


# ------------------------------------------- whole-codebase lifecycle audit
EXPENSIVE_METHODS = {
    "send_message", "edit_message", "delete_message", "send_modal", "edit",
    "edit_role", "edit_channel", "edit_guild", "create_role", "create_text_channel",
    "create_voice_channel", "create_category", "create_dm", "create_invite",
    "create_emoji", "create_webhook", "add_roles", "remove_roles", "set_permissions",
    "overwrites", "fetch", "fetch_member", "fetch_roles", "fetch_channel",
    "fetch_guild", "get_member", "get_role", "get_channel", "get_guild", "get_user",
    "ban", "kick", "unban", "timeout", "move", "clone", "delete", "remove",
    "add_tags", "edit_profile", "edit_self", "wait_until_ready", "send", "send_to",
    "purge", "add_cog", "remove_cog", "unload_extension",
}
CHEAP_PREFIXES = ("self.db.", "self.bot.db.", "bot.db.")
BRANCH = (ast.If, ast.For, ast.AsyncFor, ast.While, ast.Try, ast.Match)


def _is_expensive(await_node):
    target = await_node.value if isinstance(await_node, ast.Await) else await_node
    if ast.unparse(target).startswith(CHEAP_PREFIXES):
        return False
    f = target.func if isinstance(target, ast.Call) else target
    if not isinstance(f, ast.Attribute):
        return False
    recv = ast.unparse(f.value)
    if recv == "cursor" or recv.endswith(".cursor") or recv.endswith(".db") or recv == "db":
        return False
    return f.attr in EXPENSIVE_METHODS


def _is_initial_send(node):
    return (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and node.func.attr == "send_message" and "response" in ast.unparse(node.func))


def _straight_sends(body):
    total = 0
    for stmt in body:
        if isinstance(stmt, BRANCH):
            continue
        if isinstance(stmt, (ast.With, ast.AsyncWith)):
            total += _straight_sends(stmt.body)
            continue
        for x in ast.walk(stmt):
            if isinstance(x, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if _is_initial_send(x):
                total += 1
    return total


def _is_command(fn):
    return any(
        isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute)
        and (d.func.attr == "command" or d.func.attr.endswith("_command"))
        for d in fn.decorator_list
    )


def _command_callbacks(path):
    """Every slash-command callback: cog methods AND module-level commands
    (bot.py registers /help and /status on bot.tree directly)."""
    tree = ast.parse(read(path))
    bodies = [tree.body]
    bodies += [c.body for c in ast.walk(tree) if isinstance(c, ast.ClassDef)]
    for body in bodies:
        for fn in [n for n in body
                   if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
            if _is_command(fn):
                yield fn


def _python_files():
    for sub in ("", "cogs", "utils"):
        d = os.path.join(ROOT, sub) if sub else ROOT
        if not os.path.isdir(d):
            continue
        for f in sorted(os.listdir(d)):
            if f.endswith(".py"):
                yield os.path.join(d, f)


@pytest.mark.parametrize("path", list(_python_files()),
                         ids=lambda p: os.path.relpath(p, ROOT))
def test_python_file_compiles(path):
    """These tests parse source instead of importing it, so a SyntaxError would
    otherwise sail straight through the suite."""
    compile(read(path), path, "exec")


@pytest.mark.parametrize("path", list(_python_files()),
                         ids=lambda p: os.path.relpath(p, ROOT))
def test_no_command_awaits_rest_before_responding(path):
    """No command may perform Discord REST calls before answering the
    interaction; Discord expires it after 3 seconds."""
    offenders = []
    for fn in _command_callbacks(path):
        has_defer = any(isinstance(n, ast.Attribute) and n.attr == "defer"
                        for n in ast.walk(fn))
        pricey = [n for n in ast.walk(fn) if isinstance(n, ast.Await) and _is_expensive(n)]
        if not pricey or has_defer:
            continue
        resp = [n.lineno for n in ast.walk(fn) if _is_initial_send(n)]
        if resp and any(n.lineno < min(resp) for n in pricey):
            offenders.append(fn.name)
    assert not offenders, (
        f"{os.path.relpath(path, ROOT)}: {offenders} await Discord API calls "
        "before responding and never defer() - will time out after 3s"
    )


@pytest.mark.parametrize("path", list(_python_files()),
                         ids=lambda p: os.path.relpath(p, ROOT))
def test_no_command_never_responds(path):
    offenders = []
    for fn in _command_callbacks(path):
        answered = False
        for n in ast.walk(fn):
            if isinstance(n, ast.Attribute) and n.attr == "defer":
                answered = True
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute):
                src = ast.unparse(n.func)
                if (n.func.attr == "send" and "followup" in src) or _is_initial_send(n):
                    answered = True
        if not answered:
            offenders.append(fn.name)
    assert not offenders, (
        f"{os.path.relpath(path, ROOT)}: {offenders} never answer the interaction"
    )


@pytest.mark.parametrize("path", list(_python_files()),
                         ids=lambda p: os.path.relpath(p, ROOT))
def test_no_command_responds_twice_inline(path):
    offenders = [fn.name for fn in _command_callbacks(path)
                 if _straight_sends(fn.body) >= 2]
    assert not offenders, (
        f"{os.path.relpath(path, ROOT)}: {offenders} call response.send_message "
        "twice on one path -> InteractionAlreadyResponded"
    )