# iOS Tweak Translator (starter)

A GitHub Actions starter that accepts a jailbreak tweak `.deb`, extracts it, translates
supported user-facing strings from Chinese to English, rebuilds the package, and uploads
the result as an Actions artifact.

## What it handles

- GNU `ar`/Debian `.deb` packages using Ubuntu's `dpkg-deb`.
- `.strings` key/value files (preserves keys; translates values).
- XML or binary `.plist` files (translates strings only under likely UI keys such as
  `label`, `title`, `footerText`, `message`, `placeholder`, `prompt`, `name`,
  `description`, `buttonTitle`, and `text`).
- `.json` files (same conservative UI-key rule).
- Scans other package files for Chinese and reports them. It does **not** rewrite
  compiled `.dylib`/executables, images, archives, or arbitrary source code.

## Setup

1. Create a GitHub repository and upload these files.
2. In the repository, open **Settings → Secrets and variables → Actions → New repository secret**.
3. Add `OPENAI_API_KEY` with an API key that has API billing enabled.
4. Open **Actions → Translate iOS Tweak → Run workflow**.
5. Enter the exact filename of a `.deb` committed under `input/`, e.g. `ExampleTweak.deb`.
6. Download the generated `.deb` and report from the workflow run's **Artifacts** section.

> API usage is billable separately from a ChatGPT subscription. Do not commit API keys.
> The workflow does not automatically publish packages to a repo or install them.

## Add a package

Put the package in `input/` and commit it. For private tweaks, use a private repository
and check that you are permitted to modify and redistribute the package.

## Important limitations

- This is a conservative first version. It deliberately avoids changing bundle IDs,
  preference specifiers, selectors, class names, file paths, package metadata, or
  compiled binaries.
- Some preference plists use keys other than the UI-key allowlist. Inspect `report.md`
  and extend `UI_KEYS` in `scripts/translate_package.py` only after reviewing the plist.
- `.stringsdict`, storyboard, nib, Swift/Objective-C hard-coded strings, images, and
  obfuscated/encrypted resources are not translated in this starter.
- The package is rebuilt, not re-signed. Most rootless/rootful tweak packages do not
  use IPA-style signing, but test the output in a safe environment.
- Always keep the original `.deb`. Install at your own risk and check dependencies,
  architecture, rootless/rootful paths, and package metadata before using it.

## Local run (Ubuntu/Debian)

Install `dpkg-dev`, `python3`, and `python3-pip`, set `OPENAI_API_KEY`, then:

```bash
python3 scripts/translate_package.py input/ExampleTweak.deb --output output
```

The script writes the rebuilt package and `report.md` under `output/`.
