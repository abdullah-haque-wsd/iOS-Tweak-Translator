#!/usr/bin/env python3
"""Conservative Chinese -> English translator for selected iOS tweak resources."""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path
import plistlib

CHINESE_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")
# Only values associated with these keys are translated in plist/json structures.
UI_KEYS = {
    "label", "title", "footertext", "description", "name", "placeholder",
    "prompt", "message", "buttontitle", "text", "detailtext", "header",
    "subtitle", "valuedescription", "alerttitle", "alertmessage",
}
SKIP_SUFFIXES = {
    ".dylib", ".so", ".a", ".deb", ".ipa", ".png", ".jpg", ".jpeg",
    ".gif", ".car", ".nib", ".storyboardc", ".framework", ".zip",
    ".gz", ".xz", ".bz2", ".lzma", ".sqlite", ".db",
}
STRINGS_PAIR = re.compile(
    r'(?P<prefix>\s*(?:(?://[^\n]*|/\*.*?\*/)\s*)*)'
    r'"(?P<key>(?:\\.|[^"\\])*)"\s*=\s*"(?P<value>(?:\\.|[^"\\])*)"\s*;',
    re.S,
)

def has_chinese(value: str) -> bool:
    return bool(CHINESE_RE.search(value))

def unescape_strings(s: str) -> str:
    # .strings files use C-style quoted strings.
    try:
        return bytes(s, "utf-8").decode("unicode_escape")
    except Exception:
        return s

def escape_strings(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\r", "\\r")

class Translator:
    def __init__(self, dictionary: dict[str, str]):
        self.dictionary = dictionary
        self.cache = dict(dictionary)
        self.api_key = os.environ.get("OPENAI_API_KEY")
        self.model = os.environ.get("OPENAI_MODEL", "gpt-4.1-mini")

    def translate_many(self, values: list[str], context: str) -> dict[str, str]:
        todo = list(dict.fromkeys(v for v in values if has_chinese(v) and v not in self.cache))
        if todo and not self.api_key:
            raise RuntimeError("Chinese strings need translation, but OPENAI_API_KEY is not set.")
        # Small batches keep requests manageable and reduce context confusion.
        for start in range(0, len(todo), 30):
            batch = todo[start:start + 30]
            prompt = {
                "task": "Translate the Chinese user-interface strings into concise, natural English.",
                "context": context,
                "rules": [
                    "Return JSON only: an object mapping each exact source string to its English translation.",
                    "Preserve placeholders, format tokens, punctuation, numbers, and product/proper names.",
                    "Do not translate identifiers or invent meaning. Keep ambiguous terms concise and literal.",
                    "Translate every supplied string; do not omit keys."
                ],
                "strings": batch,
            }
            body = json.dumps({
                "model": self.model,
                "temperature": 0.1,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": "You are a careful software localization translator. Output valid JSON only."},
                    {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)}
                ],
            }).encode()
            req = urllib.request.Request(
                "https://api.openai.com/v1/chat/completions",
                data=body,
                headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=90) as response:
                payload = json.loads(response.read().decode("utf-8"))
            result = json.loads(payload["choices"][0]["message"]["content"])
            for source in batch:
                translated = result.get(source)
                if isinstance(translated, str) and translated.strip():
                    self.cache[source] = translated.strip()
                else:
                    self.cache[source] = source
        return {v: self.cache.get(v, v) for v in values}

def load_dictionary(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))

def translate_strings_file(path: Path, translator: Translator, report: list[str]) -> int:
    original = path.read_text(encoding="utf-8-sig", errors="replace")
    matches = list(STRINGS_PAIR.finditer(original))
    candidates = [unescape_strings(m.group("value")) for m in matches]
    mapping = translator.translate_many(candidates, f"Apple .strings localization file: {path.name}")
    count = 0
    def replace(m):
        nonlocal count
        value = unescape_strings(m.group("value"))
        new = mapping.get(value, value)
        if new != value:
            count += 1
        return f'{m.group("prefix")}"{m.group("key")}" = "{escape_strings(new)}";'
    updated = STRINGS_PAIR.sub(replace, original)
    if count:
        path.write_text(updated, encoding="utf-8")
        report.append(f"- `{path}`: translated {count} value(s) in `.strings`.")
    return count

def walk_values(obj, key=None, found=None):
    if found is None:
        found = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            walk_values(v, str(k), found)
    elif isinstance(obj, list):
        for v in obj:
            walk_values(v, key, found)
    elif isinstance(obj, str) and key and key.casefold() in UI_KEYS and has_chinese(obj):
        found.append(obj)
    return found

def replace_values(obj, mapping, key=None):
    if isinstance(obj, dict):
        return {k: replace_values(v, str(k), mapping) for k, v in obj.items()}
    if isinstance(obj, list):
        return [replace_values(v, key, mapping) for v in obj]
    if isinstance(obj, str) and key and key.casefold() in UI_KEYS:
        return mapping.get(obj, obj)
    return obj

def translate_structured_file(path: Path, translator: Translator, report: list[str]) -> int:
    try:
        if path.suffix.lower() == ".plist":
            with path.open("rb") as f:
                obj = plistlib.load(f)
        else:
            obj = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        report.append(f"- `{path}`: could not parse; left unchanged ({exc}).")
        return 0
    candidates = walk_values(obj)
    if not candidates:
        return 0
    mapping = translator.translate_many(candidates, f"iOS tweak preference/resource file: {path.name}")
    updated = replace_values(obj, mapping)
    changed = sum(1 for s in candidates if mapping.get(s, s) != s)
    if changed:
        if path.suffix.lower() == ".plist":
            with path.open("wb") as f:
                plistlib.dump(updated, f, fmt=plistlib.FMT_XML, sort_keys=False)
        else:
            path.write_text(json.dumps(updated, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        report.append(f"- `{path}`: translated {changed} UI value(s).")
    return changed

def scan_chinese(root: Path) -> list[str]:
    hits = []
    for p in root.rglob("*"):
        if not p.is_file() or p.suffix.lower() in SKIP_SUFFIXES:
            continue
        try:
            data = p.read_bytes()
            text = data.decode("utf-8", errors="ignore")
        except OSError:
            continue
        if has_chinese(text):
            hits.append(str(p.relative_to(root)))
    return hits

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("deb", type=Path)
    parser.add_argument("--output", type=Path, default=Path("output"))
    parser.add_argument("--dictionary", type=Path, default=Path("translations/dictionary.json"))
    args = parser.parse_args()
    deb = args.deb.resolve()
    if not deb.is_file() or deb.suffix.lower() != ".deb":
        parser.error("Input must be an existing .deb file.")
    if shutil.which("dpkg-deb") is None:
        raise SystemExit("dpkg-deb not found. Install dpkg-dev/dpkg.")
    args.output.mkdir(parents=True, exist_ok=True)
    report = ["# Translation report", "", f"- Input: `{deb.name}`", ""]
    dictionary = load_dictionary(args.dictionary)
    translator = Translator(dictionary)

    with tempfile.TemporaryDirectory(prefix="tweak-translate-") as tmp:
        work = Path(tmp)
        payload, control = work / "payload", work / "control"
        payload.mkdir(); control.mkdir()
        subprocess.run(["dpkg-deb", "-x", str(deb), str(payload)], check=True)
        subprocess.run(["dpkg-deb", "-e", str(deb), str(control)], check=True)

        translated = 0
        for path in payload.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix.lower() == ".strings":
                translated += translate_strings_file(path, translator, report)
            elif path.suffix.lower() in {".plist", ".json"}:
                translated += translate_structured_file(path, translator, report)

        remaining = scan_chinese(payload)
        report += ["", "## Remaining files containing Chinese", ""]
        if remaining:
            report += [f"- `{p}`" for p in remaining]
            report.append("")
            report.append("These are scan hits, not proof every character is user-facing. Compiled binaries and unsupported formats are intentionally not modified.")
        else:
            report.append("No remaining Chinese text detected by the basic UTF-8 scan.")
        report += ["", f"## Summary", "", f"- Translated values: **{translated}**", f"- Remaining scan-hit files: **{len(remaining)}**", ""]
        # Save updated translation cache/dictionary for repeat terminology consistency.
        args.dictionary.parent.mkdir(parents=True, exist_ok=True)
        args.dictionary.write_text(json.dumps(translator.cache, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        control_files = list(control.iterdir())
        for item in control_files:
            shutil.copy2(item, payload / "DEBIAN" / item.name) if (payload / "DEBIAN").is_dir() else None
        # dpkg-deb -b expects control metadata in a DEBIAN directory.
        debian_dir = payload / "DEBIAN"
        debian_dir.mkdir(exist_ok=True)
        for item in control.iterdir():
            shutil.copy2(item, debian_dir / item.name)
        out_name = f"{deb.stem}-English.deb"
        out_deb = args.output / out_name
        subprocess.run(["dpkg-deb", "--build", str(payload), str(out_deb)], check=True)
        (args.output / "report.md").write_text("\n".join(report), encoding="utf-8")
        print(f"Built: {out_deb}")
        print(f"Translated values: {translated}; remaining scan-hit files: {len(remaining)}")

if __name__ == "__main__":
    main()
