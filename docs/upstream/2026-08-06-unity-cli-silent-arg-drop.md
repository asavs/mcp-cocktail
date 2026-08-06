## `unity command` silently ignores non-`--flag value` arguments and still reports success — including on mutating tools

### Environment

- `unity` CLI: `1.0.0-beta.3`
- Unity Editor: `6000.5.5f1`
- `com.unity.pipeline`: `0.4.0-exp.1`
- OS: Windows 11
- Editor running with the Pipeline HTTP server listening on port 7800

### Summary

`unity command <tool>` only binds arguments given in `--flag value` form. If you instead pass `key=value` form or a raw JSON object, the CLI does not error and does not bind the argument — it silently runs the tool with default parameters and reports `"success": true`. On a read tool this returns wrong data with no indication anything went wrong. On a mutating tool it means the tool executes with unintended defaults and something gets created/changed before you find out the argument never took effect.

### Steps to reproduce

Minimal case — any scene, no setup required:

```
unity command find_gameobjects --name "Main Camera" --json
unity command find_gameobjects name="Main Camera" --json
unity command find_gameobjects '{"name":"Main Camera"}' --json
```

(On Windows, run these from PowerShell, or set `MSYS_NO_PATHCONV=1` first if you are in Git
Bash — unrelated to this report, but MSYS rewrites the leading `/` of any Unity hierarchy path
argument into a Windows path, which will confuse a follow-up test using `--hierarchy_path`.)

Expected: all three either find the same object(s) named `Main Camera`, or the two non-`--flag` forms are rejected with a syntax error.

Actual: only the first form applies the `name` filter. The second and third silently drop the argument, run `find_gameobjects` with no filter, and return every GameObject in the scene — while still reporting `"success": true`.

For scale, here is the same behavior on a larger scene (662 GameObjects total, one of them named `Probe-Root`), included as supporting evidence rather than as the repro itself:

```
unity command find_gameobjects --name Probe-Root --json
→ "count": 1   (correct)

unity command find_gameobjects name=Probe-Root --json
→ "count": 662  (filter silently dropped; still "success": true)

unity command find_gameobjects '{"name":"Probe-Root"}' --json
→ "count": 662  (same)
```

### Why it matters

For a read-only tool like `find_gameobjects`, this means a script or a person can get a `"success": true` response carrying the wrong data, with nothing in the output to suggest the filter never applied.

The more serious case is mutating tools. Probing `create_gameobject` with a mis-syntaxed argument (`key=value` form instead of `--key value`) did not produce an error — it created a new `New Game Object` in the live scene using default parameters, silently ignoring the intended argument. An unrecognized or unbound argument should not be treated as "no argument was given"; it should be a hard error, and for a mutating tool that error needs to happen before anything is written to the scene.

### Two things that make this easy to hit

1. `unity command <tool> --help` does not print per-tool help. Regardless of which tool name follows `command`, it prints the generic `command` subcommand usage. This looks like it worked (it exits cleanly and prints something plausible-looking), so it's a dead end that doesn't look like one — there's no obvious signal to go find the real parameter list elsewhere.
2. The actual parameter schema (names, types, required/optional, defaults) is only available in the `parameters` array of `unity list --json`. So the path someone would naturally try first (`command <tool> --help`) and the path that actually has the schema (`list --json`) are two different commands, and the discoverable one is the wrong one. That's most of what makes the silent-drop reachable in ordinary use — someone reasonably falls back to guessing a `key=value` or JSON form when `--help` doesn't answer the question.

### Suggested fix

Worth considering: reject unrecognized or unbound arguments outright — non-zero exit, with a message naming the specific token that didn't bind — rather than falling back to defaults. And it would close the loop nicely if `unity command <tool> --help` actually printed that tool's parameter list (the data already exists in `unity list --json`, it just isn't surfaced at the point where someone would look for it).

Worth noting for contrast: the CLI's error messages elsewhere are unusually good — `unity list` names all three prerequisites when it can't reach a Pipeline server, and path-resolution failures name the exact path that was tried. This silent-drop behavior is out of character for the tool otherwise, which is part of why it's surprising to run into.
