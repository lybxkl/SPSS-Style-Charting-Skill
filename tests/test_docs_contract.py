"""文档契约测试：SKILL.md 里写出来的命令，必须真的能跑。

第一轮审计修的是"代码对但文档撒谎"，第二轮又抓到一处（`--undo` 不带日志路径，
照文档输入直接 `argument --undo: expected one argument` 退出 2）。人工核对挡不住
这类回归，因为没人会每次改文档都逐条跑一遍命令。

本测试做三件事，全部是静态检查，不依赖语料、不联网、秒级完成：

1. 命令块里出现的 `scripts/<name>.py` 必须存在；
2. 每个 `--flag` 必须在该脚本的 argparse 里存在（读 `--help`）；
3. 需要取值的 `--flag`（非 store_true / 非 count），在命令里后面必须真的跟了值——
   不能紧跟另一个 `--flag`，也不能行尾就断。
"""

import os
import re
import subprocess
import sys
import unittest

from _helpers import ROOT, SCRIPTS, SKILL

SKILL_MD = os.path.join(SKILL, "SKILL.md")

# ```bash ... ``` 或 ```powershell ... ``` 代码块
BLOCK_RE = re.compile(r"```(?:bash|powershell|sh)?\n(.*?)```", re.S)
# python scripts/xxx.py ...（允许行首 python / python3 / py）
CMD_RE = re.compile(r"^\s*(?:python3?|py)\s+scripts[\\/]([\w_]+\.py)\b(.*)$", re.M)
FLAG_RE = re.compile(r"(?<![\w-])(--[A-Za-z][A-Za-z0-9_-]*)")

# 这些 flag 出现在命令行里但不属于被调脚本（解释器/工具级）
IGNORED = {"--help"}


def _blocks():
    with open(SKILL_MD, encoding="utf-8") as fh:
        text = fh.read()
    return [b for b in BLOCK_RE.findall(text)]


def _commands():
    """产出 (script_name, rest_of_line)。续行用 \\ 拼接。"""
    out = []
    for block in _blocks():
        joined = block.replace("\\\n", " ")
        for m in CMD_RE.finditer(joined):
            script, rest = m.group(1), m.group(2)
            out.append((script, rest.split("\n")[0]))
    return out


_HELP_CACHE = {}


def _help_flags(script):
    """从 `--help` 的 usage 段解析 flag → 是否需要取值。

    只读 usage 行而不用下面的参数列表：help 正文里的元变量与描述靠列对齐区分，
    不同 argparse 版本对齐列不同；而 usage 段用的是固定文法——
    `[--flag META]` 需要取值，`[--flag]` 不需要（store_true / count）。
    """
    if script in _HELP_CACHE:
        return _HELP_CACHE[script]
    path = os.path.join(SCRIPTS, script)
    proc = subprocess.run(
        [sys.executable, path, "--help"],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120,
    )
    lines = (proc.stdout or "").splitlines()
    usage = []
    for line in lines:
        if line.startswith("usage:"):
            usage.append(line)
        elif usage and line.startswith(" " * 4) and not line.strip().startswith("-"):
            usage.append(line.strip())
        elif usage:
            break
    blob = " ".join(usage)
    flags = {}
    for flag, metavar in re.findall(r"(--[A-Za-z][\w-]*)([^\s\[\],]*)", blob):
        flags[flag] = bool(metavar)
    _HELP_CACHE[script] = flags
    return flags


class DocsContractCase(unittest.TestCase):
    def test_scripts_referenced_by_docs_exist(self):
        missing = [
            s for s, _ in _commands() if not os.path.isfile(os.path.join(SCRIPTS, s))
        ]
        self.assertEqual(sorted(set(missing)), [],
                         f"SKILL.md 提到了不存在的脚本: {sorted(set(missing))}")

    def test_every_flag_is_recognised_by_its_script(self):
        problems = []
        for script, rest in _commands():
            known = _help_flags(script)
            for flag in FLAG_RE.findall(rest):
                if flag in IGNORED:
                    continue
                if flag not in known:
                    problems.append(f"{script}: {flag} 不在 argparse 里")
        self.assertEqual(problems, [], "\n".join(problems))

    def test_flags_that_take_a_value_are_given_one(self):
        problems = []
        for script, rest in _commands():
            known = _help_flags(script)
            tokens = rest.split()
            for i, tok in enumerate(tokens):
                if not tok.startswith("--"):
                    continue
                flag = tok.split("=", 1)[0]
                if flag in IGNORED or not known.get(flag):
                    continue
                if "=" in tok:
                    continue
                nxt = tokens[i + 1] if i + 1 < len(tokens) else ""
                if nxt == "" or nxt.startswith("--"):
                    problems.append(f"{script}: {flag} 需要取值，但命令里后面没有值")
        self.assertEqual(problems, [], "\n".join(problems))

    def test_undo_documented_with_its_log_path(self):
        """回归 REP-04：--undo 必须跟 move_log.csv 的路径。"""
        hits = [
            (script, rest)
            for script, rest in _commands()
            if "dedupe_corpus.py" == script and "--undo" in rest
        ]
        self.assertTrue(hits, "SKILL.md 里应当留一条 --undo 的示例（可回滚性要能被查到）")
        for _script, rest in hits:
            after = rest.split("--undo", 1)[1].strip()
            self.assertTrue(
                after and not after.startswith("--"),
                f"--undo 后面没有跟日志路径: {rest.strip()}",
            )


if __name__ == "__main__":
    unittest.main()